# analytics/views.py
from django.db.models import Sum, Count, F, Q, Avg
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from accounts.permissionsUsers import IsSeller
from orders.models import OrderItem, OrderStatus
from products.models import Product
from returns.models import ReturnRequest, ReturnStatus
from reviews.models import Review
from wallet.models import Wallet, Transaction
from decimal import Decimal
from datetime import timedelta

class SellerDashboardSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def get(self, request):
        seller = request.user
        now = timezone.now()
        start_30 = now - timedelta(days=30)

        # Completed orders (funds released) → revenue to seller
        completed_items = (OrderItem.objects
            .filter(seller=seller, order__status=OrderStatus.COMPLETED))

        revenue_all = completed_items.aggregate(v=Sum('total_price'))['v'] or Decimal('0.00')
        orders_all = (completed_items.values('order_id').distinct().count())
        items_all = completed_items.aggregate(c=Sum('quantity'))['c'] or 0
        aov = (revenue_all / orders_all) if orders_all else Decimal('0.00')

        # Last 30d stats
        completed_items_30 = completed_items.filter(order__completed_at__gte=start_30)
        revenue_30 = completed_items_30.aggregate(v=Sum('total_price'))['v'] or Decimal('0.00')
        orders_30 = completed_items_30.values('order_id').distinct().count()

        # Refund rate = refunded qty / sold qty (last 30d)
        sold_qty_30 = completed_items_30.aggregate(c=Sum('quantity'))['c'] or 0
        refunded_qty_30 = (ReturnRequest.objects
                           .filter(order_item__seller=seller,
                                   status=ReturnStatus.APPROVED,
                                   processed_at__gte=start_30)
                           .aggregate(c=Sum('quantity'))['c'] or 0)
        refund_rate_30 = (refunded_qty_30 / sold_qty_30) if sold_qty_30 else 0

        # Low stock
        LOW_STOCK = 5
        low_stock_count = Product.objects.filter(seller=seller, quantity__lte=LOW_STOCK).count()

        # Rating avg
        rating_avg = (Review.objects
                      .filter(product__seller=seller)
                      .aggregate(a=Avg('rating'))['a']) or 0

        # Wallet
        wallet = Wallet.objects.filter(user=seller).first()
        wallet_summary = {
            "balance": str(wallet.balance if wallet else Decimal('0.00')),
            "held_balance": str(wallet.held_balance if wallet else Decimal('0.00')),
        }

        # Points & rank (if you added rank helper)
        points = getattr(seller, 'points', 0)
        is_verified = getattr(seller, 'is_verified_seller', False)
        rank = "gold" if points >= 2000 else "silver" if points >= 500 else "starter"

        return Response({
            "kpis": {
                "revenue_all": str(revenue_all),
                "orders_all": orders_all,
                "items_all": items_all,
                "avg_order_value": str(aov),
                "revenue_30d": str(revenue_30),
                "orders_30d": orders_30,
                "refund_rate_30d": round(refund_rate_30, 3),
                "low_stock_count": low_stock_count,
                "rating_avg": round(float(rating_avg), 2),
                "points": points,
                "rank": rank,
                "is_verified_seller": is_verified,
            },
            "wallet": wallet_summary
        })

class SellerOrdersOverTimeView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def get(self, request):
        seller = request.user
        # group by date
        qs = (OrderItem.objects
              .filter(seller=seller, order__status=OrderStatus.COMPLETED)
              .values('order__completed_at__date')
              .annotate(
                  revenue=Sum('total_price'),
                  orders=Count('order', distinct=True),
                  items=Sum('quantity'))
              .order_by('order__completed_at__date'))
        data = [{
            "date": r['order__completed_at__date'],
            "revenue": float(r['revenue'] or 0),
            "orders": r['orders'],
            "items": r['items'] or 0
        } for r in qs]
        return Response(data)

class SellerTopProductsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def get(self, request):
        seller = request.user
        limit = int(request.query_params.get('limit', 10))
        qs = (OrderItem.objects
              .filter(seller=seller, order__status=OrderStatus.COMPLETED)
              .values('product_id', 'product__name_en', 'product__name_ar')
              .annotate(revenue=Sum('total_price'), qty=Sum('quantity'))
              .order_by('-revenue')[:limit])
        return Response([{
            "product_id": r['product_id'],
            "name_en": r['product__name_en'],
            "name_ar": r['product__name_ar'],
            "revenue": float(r['revenue'] or 0),
            "quantity": r['qty'] or 0
        } for r in qs])

class SellerLowStockView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def get(self, request):
        seller = request.user
        LOW_STOCK = int(request.query_params.get('threshold', 5))
        qs = (Product.objects
              .filter(seller=seller, quantity__lte=LOW_STOCK)
              .values('id', 'name_en', 'name_ar', 'quantity')
              .order_by('quantity', 'id'))
        return Response(list(qs))

class SellerReturnsStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def get(self, request):
        seller = request.user
        qs = (ReturnRequest.objects
              .filter(order_item__seller=seller, status=ReturnStatus.APPROVED)
              .values('reason')
              .annotate(total=Sum('quantity'))
              .order_by('-total'))
        total_qty = sum(r['total'] or 0 for r in qs)
        return Response({
            "total_returned_qty": total_qty,
            "by_reason": [{"reason": r['reason'], "qty": r['total']} for r in qs],
        })

class SellerRatingsBreakdownView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def get(self, request):
        seller = request.user
        # counts per star 1..5
        from reviews.models import Review
        buckets = {i: 0 for i in range(1, 6)}
        agg = (Review.objects
               .filter(product__seller=seller)
               .values('rating')
               .annotate(c=Count('id')))
        for row in agg:
            buckets[row['rating']] = row['c']
        avg = (Review.objects
               .filter(product__seller=seller)
               .aggregate(a=Avg('rating'))['a']) or 0
        return Response({"avg": round(float(avg), 2), "buckets": buckets})

class SellerAuctionStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def get(self, request):
        from auctions.models import Auction, AuctionStatus
        seller = request.user
        total = Auction.objects.filter(seller=seller).count()
        by_status = (Auction.objects
                     .filter(seller=seller)
                     .values('status')
                     .annotate(c=Count('id')))
        return Response({
            "total": total,
            "by_status": {row['status']: row['c'] for row in by_status}
        })

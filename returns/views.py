from rest_framework import generics, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from orders.models import Order, OrderStatus
from collections import defaultdict
from .models import ReturnRequest, ReturnRequestImage, ReturnStatus, ProductCondition
from rest_framework.pagination import PageNumberPagination
from .serializers import (
    ReturnRequestSerializer,
    ReturnRequestCreateSerializer,
    ReturnRequestImageSerializer,
    ReturnedProductSerializer,
    ReturnRequestImageUploadSerializer
)
from orders.models import OrderItem
from wallet.models import Wallet, Transaction
from django.utils import timezone
from notifications.models import Notification
from decimal import Decimal
from .models import ReturnRequest, ReturnedProduct
from notifications.models import Notification
from django.core.paginator import Paginator, EmptyPage

SELLER_APPROVAL_STATUSES = ['open_box', 'used', 'missing_parts']


# For listing user's return requests
class ReturnRequestListView(generics.ListAPIView):
    serializer_class = ReturnRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        return ReturnRequest.objects.filter(buyer=self.request.user).order_by('-requested_at')

# For submitting a new return request
class ReturnRequestCreateView(generics.CreateAPIView):
    serializer_class = ReturnRequestCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        rr = serializer.save(buyer=self.request.user)

        # 🔔 Notify buyer (confirmation)
        Notification.objects.create(
            user=rr.buyer,
            notification_type='refund_requested',  # reuse existing choice
            message_ar=f"تم إنشاء طلب إرجاع لعنصر الطلب #{rr.order_item_id}.",
            message_en=f"Your return request was created for order item #{rr.order_item_id}.",
            content_object=rr,
        )

        # 🔔 Notify seller (heads-up)
        seller = rr.order_item.product.seller
        Notification.objects.create(
            user=seller,
            notification_type='refund_requested',
            message_ar=f"تم إنشاء طلب إرجاع لمنتجك ({rr.order_item.product.name_ar}) بكمية {rr.quantity}.",
            message_en=f"A return request was created for your product ({rr.order_item.product.name_en}), qty {rr.quantity}.",
            content_object=rr,
        )

# For uploading images to a return request
class ReturnRequestImageUploadView(generics.CreateAPIView):
    serializer_class = ReturnRequestImageUploadSerializer
    permission_classes = [permissions.IsAuthenticated]
    def perform_create(self, serializer):
        return_request_id = self.kwargs.get('return_request_id')
        return_request = ReturnRequest.objects.get(pk=return_request_id, buyer=self.request.user)
        serializer.save(return_request=return_request)

# For admin/delivery staff to update the status, notes, condition, and refund amount
class MultiStatusReturnProcessView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, return_request_id):
        return_request = ReturnRequest.objects.get(pk=return_request_id)

        statuses = request.data.get('statuses', [])
        total_qty = sum(int(s['quantity']) for s in statuses)
        if total_qty != return_request.quantity:
            return Response(
                {'error': f'Total assigned quantity ({total_qty}) does not match the quantity to be returned ({return_request.quantity}).'},
                status=400
            )

        # Store the inspection results in the return request itself
        return_request.inspection_notes = f"Inspection results: {statuses}"
        return_request.status = ReturnStatus.UNDER_INSPECTION
        return_request.save()

        # Store the statuses data in the session or a temporary field for later use
        # This is a simplified approach - you might want to use a more robust method
        request.session[f'return_{return_request_id}_statuses'] = statuses

        # Notify seller for statuses that require approval
        SELLER_APPROVAL_STATUSES = {'open_box', 'used'}
        for s in statuses:
            qty = int(s.get('quantity', 0))
            if qty <= 0:
                continue

            status_str = s['status']
            if status_str in SELLER_APPROVAL_STATUSES:
                Notification.objects.create(
                    user=return_request.order_item.product.seller,
                    notification_type='return_status_update',
                    message_ar=f"تم تسجيل نتيجة الفحص (قيد الموافقة): {qty} قطعة بحالة {status_str.replace('_', ' ')}.",
                    message_en=f"Inspection result recorded (pending approval): {qty} unit(s) as {status_str.replace('_', ' ')}.",
                    content_object=return_request,
                )

        # Notify buyer
        Notification.objects.create(
            user=return_request.buyer,
            notification_type='return_status_update_buyer',
            message_ar="تم تسجيل نتيجة الفحص لطلب الإرجاع — بانتظار القرار النهائي.",
            message_en="Inspection results recorded for your return — awaiting final decision.",
            content_object=return_request,
        )

        return Response({'message': 'Inspection results recorded. Awaiting final approval.'}, status=200)

class ReturnRequestAdminUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        try:
            return_request = ReturnRequest.objects.get(pk=pk)
        except ReturnRequest.DoesNotExist:
            return Response({'error': 'Return request not found.'}, status=404)

        status_ = request.data.get('status')
        valid_statuses = [ReturnStatus.APPROVED, ReturnStatus.REJECTED]
        if status_ not in valid_statuses:
            return Response({'error': 'Invalid status. Only APPROVED or REJECTED allowed.'}, status=400)

        # Optional admin fields
        return_request.admin_notes = request.data.get('admin_notes') or return_request.admin_notes
        return_request.inspection_notes = request.data.get('inspection_notes') or return_request.inspection_notes
        condition = request.data.get('condition')
        if condition:
            return_request.condition = condition

        return_request.status = status_
        return_request.inspected_by = request.user
        return_request.processed_at = timezone.now()
        
        # -------- FINALIZE ONLY IF APPROVED --------
        if status_ == ReturnStatus.APPROVED:
            # Get the inspection results from the session or request data
            statuses = request.data.get('statuses', [])
            if not statuses:
                # Try to get from session if not in request
                statuses = request.session.get(f'return_{pk}_statuses', [])
            
            if not statuses:
                return Response({'error': 'No inspection data found. Please provide statuses.'}, status=400)
            
            total_qty = sum(int(s['quantity']) for s in statuses)
            if total_qty != return_request.quantity:
                return Response(
                    {'error': f'Total assigned quantity ({total_qty}) does not match the quantity to be returned ({return_request.quantity}).'},
                    status=400
                )

            # Create ReturnedProduct records only when approved
            for s in statuses:
                qty = int(s.get('quantity', 0))
                if qty <= 0:
                    continue

                status_code = s['status']
                ReturnedProduct.objects.update_or_create(
                    product=return_request.order_item.product,
                    return_request=return_request,
                    status=status_code,
                    defaults={
                        'quantity': qty,
                        'discount_percentage': s.get('discount_percentage'),
                        'is_sellable': False,
                        'seller_approval': None,
                        'notes': s.get('notes', ''),
                    }
                )

            # 1) Figure out how many units were accepted in total
            rps = ReturnedProduct.objects.filter(return_request=return_request)
            total_returned_qty = sum(int(rp.quantity) for rp in rps)

            # 2) Auto-calc refund if not provided
            refund_amount = request.data.get('refund_amount', None)
            if refund_amount is None:
                unit_price = return_request.order_item.price_at_purchase
                refund_amount = unit_price * total_returned_qty

            # Persist refund amount
            from decimal import Decimal
            if isinstance(refund_amount, float):
                refund_amount = Decimal(str(refund_amount))
            elif isinstance(refund_amount, str):
                refund_amount = Decimal(refund_amount)
            return_request.refund_amount = refund_amount

            # 3) Move stock for 'new' portion
            new_row = rps.filter(status='new').first()
            if new_row and new_row.quantity > 0:
                product = return_request.order_item.product
                product.quantity = product.quantity + int(new_row.quantity)
                product.save()

            # 4) Refund the buyer wallet
            process_refund_and_restock(return_request)

            # 5) Apply penalties to seller based on bad conditions
            try:
                from .utils import compute_penalty_points
                seller = return_request.order_item.product.seller
                penalty_points = compute_penalty_points(return_request)
                if penalty_points > 0 and hasattr(seller, "deduct_seller_points"):
                    before = getattr(seller, "points", 0)
                    seller.deduct_seller_points(penalty_points)
                    after = seller.points
                    Notification.objects.create(
                        user=seller,
                        notification_type='seller_points_penalty',
                        message_ar=(
                            f"تم خصم {penalty_points} نقطة بسبب إرجاع منتجات تالفة/أجزاء مفقودة/غير قابلة للبيع "
                            f"في الطلب {return_request.order.order_number}. نقاطك: {before} → {after}."
                        ),
                        message_en=(
                            f"{penalty_points} points were deducted due to damaged/missing/unsaleable returns "
                            f"in order {return_request.order.order_number}. Points: {before} → {after}."
                        ),
                        content_object=return_request,
                    )
            except Exception:
                # If you haven't created the utils yet, skip silently or log
                pass

            # 6) END NOTIFICATIONS ONLY (buyer + seller summary)
            Notification.objects.create(
                user=return_request.buyer,
                notification_type='refund_approved',
                message_ar=f"تمت الموافقة على الإرجاع. سيتم رد مبلغ {return_request.refund_amount} إلى محفظتك.",
                message_en=f"Your return was approved. A refund of {return_request.refund_amount} will be applied to your wallet.",
                content_object=return_request,
            )

            # Build a concise seller summary
            parts = []
            for rp in rps:
                if int(rp.quantity) <= 0:
                    continue
                extra = f" (خصم {rp.discount_percentage}%)" if rp.discount_percentage else ""
                parts.append(f"{rp.quantity}× {rp.get_status_display()}{extra}")
            summary_ar = "تم اعتماد نتيجة الإرجاع نهائياً: " + (", ".join(parts) if parts else "بدون تفاصيل.")
            summary_en = "Return finalized: " + (", ".join([f"{rp.quantity}× {rp.get_status_display()}" + (f" ({rp.discount_percentage}%)" if rp.discount_percentage else "") for rp in rps if int(rp.quantity) > 0]) or "no details.")

            Notification.objects.create(
                user=return_request.order_item.product.seller,
                notification_type='return_status_update',
                message_ar=summary_ar,
                message_en=summary_en,
                content_object=return_request,
            )

        # -------- REJECTED --------
        elif status_ == ReturnStatus.REJECTED:
            Notification.objects.create(
                user=return_request.buyer,
                notification_type='refund_rejected',
                message_ar=f"تم رفض الإرجاع. السبب: {return_request.admin_notes or 'غير محدد'}",
                message_en=f"Your return was rejected. Reason: {return_request.admin_notes or 'Not specified'}",
                content_object=return_request,
            )

        return_request.save()
        return Response(ReturnRequestSerializer(return_request).data, status=200)
    
class ReturnRequestRejectView(APIView):
    # permission_classes = [permissions.IsAdminUser] this should be done by the delivery
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            return_request = ReturnRequest.objects.get(pk=pk)
        except ReturnRequest.DoesNotExist:
            return Response({'error': 'Return request not found.'}, status=404)
        if return_request.status in ['rejected', 'approved']:
            return Response({'error': 'Already processed.'}, status=400)
        reason = request.data.get('reason', '')
        if not reason:
            return Response({'error': 'A reason is required.'}, status=400)
        return_request.status = 'rejected'
        return_request.admin_notes = reason
        return_request.save()
        # Notify buyer
        Notification.objects.create(
            user=return_request.buyer,
            notification_type='refund_rejected',
            message_ar=f"تم رفض طلب الإرجاع الخاص بك. السبب: {reason}",
            message_en=f"Your return request was rejected. Reason: {reason}",
            content_object=return_request,
        )
        return Response({'message': 'Return request rejected and buyer notified.'}, status=200)

class RefundWholeOrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_id):
        user = request.user
        try:
            order = Order.objects.get(pk=order_id, buyer=user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Explicit blocks
        if order.status == OrderStatus.COMPLETED:
            return Response(
                {'error': 'Order is completed and can no longer be refunded.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if order.status != OrderStatus.DELIVERED:
            return Response(
                {'error': 'Only delivered orders can be refunded.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not order.is_refundable:
            return Response(
                {'error': 'Refund window has expired.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        results = []
        for item in order.items.all():
            already_returned_qty = sum(rr.quantity for rr in ReturnRequest.objects.filter(order_item=item, buyer=user))
            remaining = item.quantity - already_returned_qty
            if remaining <= 0:
                results.append({'order_item': item.id, 'status': 'already refunded'})
                continue

            rr = ReturnRequest.objects.create(
                order=order,
                order_item=item,
                buyer=order.buyer,  # important
                quantity=remaining,
                reason=request.data.get('reason', 'Refunding entire order'),
                status=ReturnStatus.REQUESTED
            )

            Notification.objects.create(
                user=order.buyer,
                notification_type='refund_requested',
                message_ar=f"تم إنشاء طلب إرجاع للعنصر #{item.id} بكمية {rr.quantity}.",
                message_en=f"Return request created for order item #{item.id} with quantity {rr.quantity}.",
                content_object=rr,
            )

            # 🔔 Notify seller
            Notification.objects.create(
                user=item.product.seller,
                notification_type='refund_requested',
                message_ar=f"تم إنشاء طلب إرجاع لمنتجك ({item.product.name_ar}) بكمية {rr.quantity}.",
                message_en=f"A return request was created for your product ({item.product.name_en}), qty {rr.quantity}.",
                content_object=rr,
            )

            results.append({'order_item': item.id, 'status': 'requested', 'return_request_id': rr.id})

        return Response({'results': results}, status=status.HTTP_201_CREATED)

def process_refund_and_restock(return_request):
    # Only handle refund wallet + transaction
    wallet = Wallet.objects.select_for_update().get(user=return_request.buyer)
    refund_amount = return_request.refund_amount or Decimal('0.00')
    if isinstance(refund_amount, float):
        refund_amount = Decimal(str(refund_amount))

    wallet.balance += refund_amount
    wallet.save()

    Transaction.objects.create(
        wallet=wallet,
        amount=refund_amount,
        transaction_type=Transaction.TransactionType.REFUND,
        description=f"Refund for ReturnRequest #{return_request.id}",
        reference=f"RETURN_{return_request.id}",
        return_request=return_request
    )

# Optionally, list all return requests for admin
class ReturnRequestAdminListView(generics.ListAPIView):
    serializer_class = ReturnRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        grouped = defaultdict(list)

        for rr in queryset:
            grouped[rr.order_id].append(ReturnRequestSerializer(rr).data)

        result = []
        for order_id, items in grouped.items():
            order = items[0]['order']  # same for all
            buyer = items[0]['buyer']  # same for all
            result.append({
                "order_id": order_id,
                "buyer": buyer,
                "items": items
            })

        return Response(result)

    def get_queryset(self):
        return ReturnRequest.objects.all().order_by('-requested_at')
    
def notify_seller_for_approval(seller, return_request):
    Notification.objects.create(
        user=seller,
        notification_type='open_box_approval',
        message_ar='لديك منتجات مرتجعة بحاجة لموافقتك على خصم السعر للبيع.',
        message_en='You have returned products needing your approval for open box/used discount sale.',
        content_object=return_request,
    )

class ReturnedProductSellerApprovalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        returned_product = ReturnedProduct.objects.get(pk=pk, product__seller=request.user)
        action = request.data.get('action')

        # Only allow approval for statuses that need it and have a discount
        if returned_product.status not in SELLER_APPROVAL_STATUSES:
            return Response({'error': 'Approval is not needed for this return type.'}, status=400)

        if returned_product.seller_approval is not None:
            return Response({'error': 'Already decided.'}, status=400)

        if action == 'accept':
            returned_product.seller_approval = True
            returned_product.is_sellable = True
            returned_product.save()
            # Notify or log as needed
        elif action == 'reject':
            returned_product.seller_approval = False
            returned_product.is_sellable = False
            returned_product.save()
            # Notify as needed
        else:
            return Response({'error': 'Invalid action.'}, status=400)

        return Response({'message': 'Decision recorded.'}, status=200)
    
class ReturnedProductsPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    
    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data
        })

class SellerReturnedProductsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        # Get query parameters for filtering
        status_filter = request.query_params.get('status', None)
        sellable_filter = request.query_params.get('is_sellable', None)
        approval_filter = request.query_params.get('seller_approval', None)  # 'pending', 'approved', 'rejected'
        product_id = request.query_params.get('product_id', None)
        date_from = request.query_params.get('date_from', None)
        date_to = request.query_params.get('date_to', None)
        
        # Base queryset
        returned_products = ReturnedProduct.objects.filter(
            product__seller=request.user
        ).select_related(
            'product',
            'return_request',
            'return_request__order',
            'return_request__order_item',
            'return_request__buyer'
        )
        
        # Apply filters
        if status_filter:
            returned_products = returned_products.filter(status=status_filter)
        
        if sellable_filter is not None:
            sellable = sellable_filter.lower() in ['true', '1', 'yes']
            returned_products = returned_products.filter(is_sellable=sellable)
        
        # Handle seller_approval filter with more intuitive values
        if approval_filter is not None:
            approval_filter = approval_filter.lower()
            if approval_filter == 'pending':
                returned_products = returned_products.filter(seller_approval__isnull=True)
            elif approval_filter == 'approved':
                returned_products = returned_products.filter(seller_approval=True)
            elif approval_filter == 'rejected':
                returned_products = returned_products.filter(seller_approval=False)
            else:
                # Fallback to exact value matching for backward compatibility
                if approval_filter in ['true', '1', 'yes']:
                    returned_products = returned_products.filter(seller_approval=True)
                elif approval_filter in ['false', '0', 'no']:
                    returned_products = returned_products.filter(seller_approval=False)
                else:
                    returned_products = returned_products.filter(seller_approval__isnull=True)
        
        if product_id:
            returned_products = returned_products.filter(product_id=product_id)
        
        if date_from:
            returned_products = returned_products.filter(created_at__gte=date_from)
        
        if date_to:
            returned_products = returned_products.filter(created_at__lte=date_to)
        
        # Order by most recent
        returned_products = returned_products.order_by('-created_at')
        
        # Use DRF pagination
        paginator = ReturnedProductsPagination()
        paginated_results = paginator.paginate_queryset(returned_products, request)
        
        # Prepare the response data
        results = []
        for rp in paginated_results:
            return_request = rp.return_request
            product = rp.product
            order = return_request.order
            order_item = return_request.order_item
            
            product_data = {
                'id': product.id,
                'name_ar': product.name_ar,
                'name_en': product.name_en,
            }
            
            return_request_data = {
                'id': return_request.id,
                'status': return_request.status,
                'status_display': return_request.get_status_display(),
                'reason': return_request.reason,
                'requested_at': return_request.requested_at,
                'processed_at': return_request.processed_at,
                'refund_amount': return_request.refund_amount,
                'admin_notes': return_request.admin_notes,
                'inspection_notes': return_request.inspection_notes,
                'condition': return_request.condition,
                'condition_display': return_request.get_condition_display() if return_request.condition else None,
            }
            
            order_data = {
                'id': order.id,
                'order_number': order.order_number,
                'created_at': order.created_at,
            }
            
            buyer_data = {
                'id': return_request.buyer.id,
                'username': return_request.buyer.username,
                'email': return_request.buyer.email,
                'phone_number': return_request.buyer.phone_number,
            }
            
            order_item_data = {
                'id': order_item.id,
                'quantity': order_item.quantity,
                'price_at_purchase': order_item.price_at_purchase,
            }
            
            # Determine if this item needs seller approval
            needs_approval = (rp.status in SELLER_APPROVAL_STATUSES and 
                             rp.discount_percentage is not None and 
                             rp.seller_approval is None)
            
            results.append({
                'returned_product_id': rp.id,
                'status': rp.status,
                'status_display': rp.get_status_display(),
                'quantity': rp.quantity,
                'discount_percentage': rp.discount_percentage,
                'is_sellable': rp.is_sellable,
                'seller_approval': rp.seller_approval,
                'seller_approval_display': self._get_approval_display(rp.seller_approval),
                'needs_approval': needs_approval,
                'notes': rp.notes,
                'created_at': rp.created_at,
                'updated_at': rp.updated_at,
                'product': product_data,
                'return_request': return_request_data,
                'order': order_data,
                'buyer': buyer_data,
                'order_item': order_item_data,
            })
        
        # Return paginated response
        return paginator.get_paginated_response(results)
    
    def _get_approval_display(self, approval_value):
        """Convert approval boolean to human-readable string"""
        if approval_value is None:
            return 'pending'
        elif approval_value:
            return 'approved'
        else:
            return 'rejected'
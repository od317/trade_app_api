# auctions/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status,generics
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction
from .models import Auction, AuctionStatus
from accounts.permissionsUsers import IsSeller, IsSuperAdminOrAdmin,IsAdmin
from products.models import Category
from .models import Auction, AuctionStatus
from rest_framework.permissions import IsAuthenticated
from .services import admin_close_auction,buy_now
from .serializers import AuctionListSerializer
from .serializers import (
    AuctionCreateSerializer, AuctionDetailSerializer,
    PlaceBidSerializer, BidSerializer, AdminDecisionSerializer
)
from rest_framework.exceptions import ValidationError as DRFValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from accounts.models import User
from products.models import Category
from .models import Auction, AuctionStatus
from .serializers import AuctionListSerializer
from .services import (
    place_bid,
    activate_scheduled_if_due,
    cancel_auction,
    admin_close_auction,
)
from accounts.permissionsUsers import IsSeller, IsSuperAdminOrAdmin,IsAdmin
from notifications.models import Notification

PUBLIC_STATUSES = [
    AuctionStatus.APPROVED,
    AuctionStatus.ACTIVE,
    AuctionStatus.ENDED,
]

class AuctionCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def post(self, request):
        ser = AuctionCreateSerializer(data=request.data, context={'request': request})
        if not ser.is_valid():
            return Response(ser.errors, status=400)
        auction = ser.save()
        Notification.objects.create(
            user=request.user,
            notification_type='auction_submitted',
            message_ar=f"تم إرسال مزادك '{auction.title}' للمراجعة.",
            message_en=f"Your auction '{auction.title}' was submitted for review.",
            content_object=auction
        )
        return Response(AuctionDetailSerializer(auction).data, status=201)

class MyAuctionsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def get(self, request):
        qs = Auction.objects.filter(seller=request.user).order_by('-created_at')
        return Response(AuctionDetailSerializer(qs, many=True).data)

class PublicAuctionListView(APIView):
    permission_classes = []  # public

    def get(self, request):
        now = timezone.now()
        qs = Auction.objects.filter(status=AuctionStatus.ACTIVE).order_by('-created_at')
        return Response(AuctionDetailSerializer(qs, many=True).data)

class AuctionDetailView(APIView):
    permission_classes = []  # public

    def get(self, request, pk):
        auction = get_object_or_404(Auction, pk=pk)
        # opportunistic activation
        activate_scheduled_if_due(auction.id)
        auction.refresh_from_db()
        return Response(AuctionDetailSerializer(auction).data)

class PlaceBidView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        ser = PlaceBidSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=400)
        amount = ser.validated_data['amount']

        try:
            bid = place_bid(pk, request.user, amount)
            return Response(BidSerializer(bid).data, status=201)

        except (DRFValidationError, DjangoValidationError) as e:
            # normalize message(s)
            detail = getattr(e, "detail", None)
            if isinstance(detail, (list, dict)):
                return Response({"errors": detail}, status=400)
            msg = str(detail or e)
            return Response({"error": msg}, status=400)

        except ValueError as e:
            return Response({"error": str(e)}, status=400)


class AdminPendingAuctionsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminOrAdmin]

    def get(self, request):
        qs = Auction.objects.filter(status=AuctionStatus.SUBMITTED).order_by('start_at')
        return Response(AuctionDetailSerializer(qs, many=True).data)

class AdminReviewAuctionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminOrAdmin]

    def post(self, request, pk):
        ser = AdminDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        action = ser.validated_data['action']
        reason = ser.validated_data.get('reason', '')

        auction = get_object_or_404(Auction, pk=pk)
        if auction.status != AuctionStatus.SUBMITTED:
            return Response({'error': 'Auction not in submitted state.'}, status=400)

        if action == 'approve':
            auction.status = AuctionStatus.APPROVED
            auction.approved_at = timezone.now()
            auction.approved_by = request.user
            auction.rejection_reason = None
            auction.save(update_fields=['status', 'approved_at', 'approved_by', 'rejection_reason'])
            Notification.objects.create(
                user=auction.seller,
                notification_type='auction_approved',
                message_ar=f"تمت الموافقة على مزادك: {auction.title}.",
                message_en=f"Your auction was approved: {auction.title}.",
                content_object=auction
            )
            # opportunistic activation if start time already passed
            activate_scheduled_if_due(auction.id)
            return Response(AuctionDetailSerializer(auction).data)
        else:
            if not reason.strip():
                return Response({'error': 'Reason is required for rejection.'}, status=400)
            auction.status = AuctionStatus.REJECTED
            auction.rejection_reason = reason.strip()
            auction.approved_at = None
            auction.approved_by = None
            auction.save(update_fields=['status', 'rejection_reason', 'approved_at', 'approved_by'])

            # restore stock on rejection
            p = auction.product
            p.quantity += 1
            p.save()

            Notification.objects.create(
                user=auction.seller,
                notification_type='auction_rejected',
                message_ar=f"تم رفض مزادك: {auction.title}. السبب: {auction.rejection_reason}",
                message_en=f"Your auction was rejected: {auction.title}. Reason: {auction.rejection_reason}",
                content_object=auction
            )
            return Response(AuctionDetailSerializer(auction).data)

class SellerCancelAuctionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSeller]

    def post(self, request, pk):
        try:
            auction = cancel_auction(pk, actor=request.user, is_admin=False)
            return Response({'status': 'cancelled', 'auction_id': auction.id})
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

class AdminCancelAuctionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminOrAdmin]

    def post(self, request, pk):
        auction = cancel_auction(pk, actor=request.user, is_admin=True)
        return Response({'status': 'cancelled', 'auction_id': auction.id})

class AdminSettleAuctionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminOrAdmin]

    def post(self, request, pk):
            # opportunistically activate, then close
            activate_scheduled_if_due(pk)
            result = admin_close_auction(pk, request.user)
            return Response(result, status=200)

class SellerMyAuctionsView(generics.ListAPIView):
    """
    GET /api/auctions/seller/mine/?status=&subcategory_id=
    """
    permission_classes = [permissions.IsAuthenticated, IsSeller]
    serializer_class = AuctionListSerializer

    def get_queryset(self):
        qs = (Auction.objects
              .filter(seller=self.request.user)
              .select_related('product', 'product__category', 'seller')
              .order_by('-created_at'))

        status_ = self.request.query_params.get('status')
        if status_:
            qs = qs.filter(status=status_)

        subcat_id = self.request.query_params.get('subcategory_id')
        if subcat_id:
            qs = qs.filter(product__category_id=subcat_id)

        return qs

class SellerSubcategoryAuctionsView(generics.ListAPIView):
    """
    GET /api/auctions/seller/subcategory/<int:subcategory_id>/?status=
    Only the seller’s auctions in a specific child category (subcategory).
    """
    permission_classes = [permissions.IsAuthenticated, IsSeller]
    serializer_class = AuctionListSerializer

    def get_queryset(self):
        subcategory_id = self.kwargs['subcategory_id']
        # ensure this is a child category (not a parent)
        subcat = get_object_or_404(Category, pk=subcategory_id)
        if subcat.parent is None:
            # it’s a parent category; we only allow child categories
            return Auction.objects.none()

        qs = (Auction.objects
              .select_related('product', 'product__category', 'seller')
              .filter(seller=self.request.user, product__category_id=subcategory_id)
              .order_by('-created_at'))

        status_ = self.request.query_params.get('status')
        if status_:
            qs = qs.filter(status=status_)

        return qs

class AdminAllAuctionsView(generics.ListAPIView):
    """
    GET /api/auctions/admin/all/?status=&seller_id=&subcategory_id=&from=&to=
    """
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminOrAdmin]
    serializer_class = AuctionListSerializer

    def get_queryset(self):
        qs = (Auction.objects
              .select_related('product', 'product__category', 'seller')
              .order_by('-created_at'))

        status_ = self.request.query_params.get('status')
        if status_:
            qs = qs.filter(status=status_)

        seller_id = self.request.query_params.get('seller_id')
        if seller_id:
            qs = qs.filter(seller_id=seller_id)

        subcat_id = self.request.query_params.get('subcategory_id')
        if subcat_id:
            qs = qs.filter(product__category_id=subcat_id)

        # optional date filters
        from_dt = self.request.query_params.get('from')
        to_dt = self.request.query_params.get('to')
        if from_dt:
            qs = qs.filter(created_at__gte=from_dt)
        if to_dt:
            qs = qs.filter(created_at__lte=to_dt)

        return qs
    
class PublicSellerAuctionsView(generics.ListAPIView):
    """
    GET /api/auctions/public/seller/<int:seller_id>/?status=&active_only=
    Public list of a seller’s auctions (approved/active/ended).
    """
    permission_classes = []  # public
    serializer_class = AuctionListSerializer

    def get_queryset(self):
        seller = get_object_or_404(User, pk=self.kwargs['seller_id'])
        qs = (Auction.objects
              .filter(seller=seller, status__in=PUBLIC_STATUSES)
              .select_related('product', 'product__category', 'seller')
              .order_by('-created_at'))

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        active_only = self.request.query_params.get('active_only')
        if active_only and active_only.lower() in ('1', 'true', 'yes'):
            qs = qs.filter(status=AuctionStatus.ACTIVE)

        return qs

class PublicSubcategoryAuctionsView(generics.ListAPIView):
    """
    GET /api/auctions/public/subcategory/<int:subcategory_id>/?status=
    Public list of auctions for a second-level (child) category.
    """
    permission_classes = []  # public
    serializer_class = AuctionListSerializer

    def get_queryset(self):
        subcat = get_object_or_404(Category, pk=self.kwargs['subcategory_id'])
        # enforce "second-level" (child) category
        if subcat.parent is None:
            # parent category => return empty queryset
            return Auction.objects.none()

        qs = (Auction.objects
              .filter(product__category=subcat, status__in=PUBLIC_STATUSES)
              .select_related('product', 'product__category', 'seller')
              .order_by('-created_at'))

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        return qs
    
class AdminCloseAuctionView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]  # Changed from IsAdmin to IsSuperAdminOrAdmin

    def post(self, request, pk):
        try:
            result = admin_close_auction(pk, request.user)
            return Response(result, status=status.HTTP_200_OK)
        except Auction.DoesNotExist:
            return Response({"error": "Auction not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
class AdminActivateAuctionView(APIView):
    permission_classes = [IsAuthenticated,IsAdmin]

    def post(self, request, pk):
        activated = activate_scheduled_if_due(pk)
        if activated:
            return Response({"detail": "Auction activated."}, status=200)
        return Response({"detail": "Auction not ready for activation."}, status=400)
    

class BuyNowView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            result = buy_now(pk, request.user)
            return Response(result, status=status.HTTP_200_OK)
        except (DRFValidationError, DjangoValidationError) as e:
            msg = getattr(e, "detail", str(e))
            return Response({"error": msg}, status=status.HTTP_400_BAD_REQUEST)
        except Auction.DoesNotExist:
            return Response({"error": "Auction not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
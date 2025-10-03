from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from .models import Review
from .serializers import (
    ReviewCreateSerializer,
    ReviewSerializer,
    ReviewUpdateSerializer,
    RatingOnlySerializer,
)
from products.models import Product


class IsOwner(permissions.BasePermission):
    """Only the author of the review can update/delete it."""
    def has_object_permission(self, request, view, obj):
        return obj.buyer_id == request.user.id


class ReviewCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = ReviewCreateSerializer(data=request.data, context={'request': request})
        try:
            ser.is_valid(raise_exception=True)
            review = ser.save()
            return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)
        except (DRFValidationError, DjangoValidationError) as e:
            return Response({'error': str(e.detail if hasattr(e, "detail") else e)}, status=400)


class RatingOnlyView(APIView):
    """Quick path: rating 1–5 only (no title/comment)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = RatingOnlySerializer(data=request.data, context={'request': request})
        try:
            ser.is_valid(raise_exception=True)
            review = ser.save()
            return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)
        except (DRFValidationError, DjangoValidationError) as e:
            return Response({'error': str(e.detail if hasattr(e, "detail") else e)}, status=400)


class ProductReviewsListView(generics.ListAPIView):
    """Public: list reviews for a product."""
    serializer_class = ReviewSerializer
    permission_classes = []
    pagination_class = None  # or use your StandardResultsSetPagination

    def get_queryset(self):
        product_id = self.kwargs['product_id']
        # Only for approved products; if you want to enforce that:
        get_object_or_404(Product, pk=product_id)  # adjust if you require is_approved=True
        return Review.objects.filter(product_id=product_id).select_related('product', 'buyer')


class MyReviewsListView(generics.ListAPIView):
    """List my own reviews (auth required)."""
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Review.objects.filter(buyer=self.request.user).select_related('product', 'order')


class ReviewDetailView(generics.RetrieveAPIView):
    """Public: read a single review."""
    queryset = Review.objects.select_related('product', 'buyer', 'order')
    serializer_class = ReviewSerializer
    permission_classes = []


class ReviewUpdateDeleteView(APIView):
    """Owner: edit or delete a review."""
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_object(self, pk):
        obj = get_object_or_404(Review.objects.select_related('product', 'buyer'), pk=pk)
        self.check_object_permissions(self.request, obj)
        return obj

    def patch(self, request, pk):
        review = self.get_object(pk)
        ser = ReviewUpdateSerializer(review, data=request.data, partial=True)
        try:
            ser.is_valid(raise_exception=True)
            review = ser.save()
            return Response(ReviewSerializer(review).data)
        except (DRFValidationError, DjangoValidationError) as e:
            return Response({'error': str(e.detail if hasattr(e, "detail") else e)}, status=400)

    def delete(self, request, pk):
        review = self.get_object(pk)
        review.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

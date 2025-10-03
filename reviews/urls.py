from django.urls import path
from .views import (
    ReviewCreateView,
    RatingOnlyView,
    ProductReviewsListView,
    MyReviewsListView,
    ReviewDetailView,
    ReviewUpdateDeleteView,
)

urlpatterns = [
    path('', ReviewCreateView.as_view(), name='review-create'),
    path('rate/', RatingOnlyView.as_view(), name='review-rate-only'),

    # lists
    path('product/<int:product_id>/', ProductReviewsListView.as_view(), name='product-reviews'),
    path('mine/', MyReviewsListView.as_view(), name='my-reviews'),

    # read / edit / delete
    path('<int:pk>/', ReviewDetailView.as_view(), name='review-detail'),
    path('<int:pk>/edit/', ReviewUpdateDeleteView.as_view(), name='review-update-delete'),
]

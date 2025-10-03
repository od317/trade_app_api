# auctions/urls.py
from django.urls import path
from .views import (
    AuctionCreateView, MyAuctionsView, PublicAuctionListView, AuctionDetailView,
    PlaceBidView, AdminPendingAuctionsView, AdminReviewAuctionView,
    SellerCancelAuctionView, AdminCancelAuctionView, AdminSettleAuctionView,SellerMyAuctionsView,
    SellerSubcategoryAuctionsView,
    AdminAllAuctionsView,PublicSellerAuctionsView,
    PublicSubcategoryAuctionsView,
    AdminCloseAuctionView,
    AdminActivateAuctionView,
    BuyNowView
)

urlpatterns = [
    # public
    path('', PublicAuctionListView.as_view(), name='auction-list'),
    path('<int:pk>/', AuctionDetailView.as_view(), name='auction-detail'),

    # seller
    path('create/', AuctionCreateView.as_view(), name='auction-create'),
    path('mine/', MyAuctionsView.as_view(), name='my-auctions'),
    path('<int:pk>/cancel/', SellerCancelAuctionView.as_view(), name='auction-cancel-seller'),

    # bidding
    path('<int:pk>/bid/', PlaceBidView.as_view(), name='auction-bid'),

    # admin
    path('admin/pending/', AdminPendingAuctionsView.as_view(), name='auction-admin-pending'),
    path('admin/<int:pk>/review/', AdminReviewAuctionView.as_view(), name='auction-admin-review'),
    path('admin/<int:pk>/cancel/', AdminCancelAuctionView.as_view(), name='auction-admin-cancel'),
    path('admin/<int:pk>/settle/', AdminSettleAuctionView.as_view(), name='auction-admin-settle'),

    path('seller/mine/', SellerMyAuctionsView.as_view(), name='seller-my-auctions'),
    path('seller/subcategory/<int:subcategory_id>/', SellerSubcategoryAuctionsView.as_view(), name='seller-subcategory-auctions'),
    path('admin/all/', AdminAllAuctionsView.as_view(), name='admin-all-auctions'),
    path('public/seller/<int:seller_id>/', PublicSellerAuctionsView.as_view(), name='public-seller-auctions'),
    path('public/subcategory/<int:subcategory_id>/', PublicSubcategoryAuctionsView.as_view(), name='public-subcategory-auctions'),
    path('admin/auctions/<int:pk>/close/', AdminCloseAuctionView.as_view(), name='auction-admin-close'),
    path('admin/<int:pk>/activate/', AdminActivateAuctionView.as_view(), name='auction-admin-activate'),

    path('<int:pk>/buy-now/', BuyNowView.as_view(), name='auction-buy-now'),
]

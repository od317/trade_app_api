from django.urls import path
from .views import BrandProductsView

from .views import (
    CreateCategoryView,
    UpdateCategoryView,
    DeleteCategoryView,LocalizedCategoryListView,
    SellerUnapprovedProductsView,
    SellerApprovedProductsView,
    SellerProductDeleteView,ProductCreateView,BlockSellerView,
    BlockedSellersListView,UnapprovedProductsView,ProductApprovalView,ProductDisapprovalView,ProductListView,
    ProductDetailView,
    CategoryProductsView,
    ProductSearchView,
    ParentCategoryListView,
    ChildCategoryListView,
    UpdateProductQuantityView,
    CartView,
    AddToCartView,
    UpdateCartItemView,
    RemoveFromCartView,
    WishlistView,
    AddToWishlistView,
    RemoveFromWishlistView,
    MoveToCartView,
    CreateSaleEventView,
    CreateProductSaleView,
    UpdateProductSaleView,
    DeleteProductSaleView,
    ActiveSaleEventListView,
    ProductsInSaleView,
    SellerProductSaleListView,
    ProductDiscountView,
    BrandListView, MyBrandRequestsView, BrandCreateView,
    BrandDetailView,
    BrandUpdateView,
    BrandDeleteView,
    AdminPendingBrandListView,
    AdminApproveBrandView,
    AdminRejectBrandView,
    BlockBrandView, 
    BlockedBrandsListView,
    UnblockBrandView,
    CategoryTopProductsView,
    SaleEventDetailView,
    TopBrandsByProductCountView,
    SellerProductsByStatusView,
    AdminProductsByStatusView,
    ProductEditRequestView,
    SellerEditRequestsView,
    EditRequestDetailView,
    AdminEditRequestsView,
    AdminApproveEditRequestView,
    AdminRejectEditRequestView,
    SellerBrandsView,
    ProductDiscountDetailView,
    UpcomingSaleEventsView,
    SellerSimplifiedApprovedProductsListView,
    SellerSalesParticipationView,
    AdminProductListView
)


urlpatterns = [
    path('LocalizedCategoryList/', LocalizedCategoryListView.as_view(), name='localized-category-list'),##  عرض الفئات حسب اللغة من الهيدر لاي شخص
    path('CreateCategory/', CreateCategoryView.as_view(), name='category-create'),
    path('UpdateCategory/<int:pk>/', UpdateCategoryView.as_view(), name='category-update'),
    path('DeleteCategory/<int:pk>/', DeleteCategoryView.as_view(), name='category-delete'),
    path('ProductCreate/<int:category_id>/', ProductCreateView.as_view(), name='ProductCreate'),##   اضافة منتج
    path('<int:product_id>/edit-request/', ProductEditRequestView.as_view(), name='product-edit-request'),
    path('seller/edit-requests/', SellerEditRequestsView.as_view(), name='seller-edit-requests'),
    path('seller/edit-requests/<int:request_id>/',EditRequestDetailView.as_view(), name='edit-request-detail'),
    path('admin/edit-requests/', AdminEditRequestsView.as_view(), name='admin-edit-requests'),
    path('admin/edit-requests/<int:request_id>/approve/', AdminApproveEditRequestView.as_view(), name='approve-edit-request'),
    path('admin/edit-requests/<int:request_id>/reject/', AdminRejectEditRequestView.as_view(), name='reject-edit-request'),##  اضافة منتج
    path('sellerproductsUnapproved/', SellerUnapprovedProductsView.as_view()),## عرض المنتجات الغير موافق عليها الخاصة بالبائع
    path('sellerproductsApproved/', SellerApprovedProductsView.as_view()),## عرض المنتجات  الموافق عليها الخاصة بالبائع
    path('sellerproductsDelete/<int:product_id>/', SellerProductDeleteView.as_view()),## حذف منتج
    path('seller/products/approved-minimal/', SellerSimplifiedApprovedProductsListView.as_view(), name='seller-approved-products-minimal'),
    path('seller/sales-participation/', SellerSalesParticipationView.as_view(), name='seller-sales-participation'),
    path('blockseller/<int:seller_id>/', BlockSellerView.as_view(), name='block-seller'),
    path('blockedsellersList/', BlockedSellersListView.as_view(), name='list-blocked-sellers'),
    path('UnapprovedProductsForAdmins/', UnapprovedProductsView.as_view(), name='UnapprovedProductsForAdmins'),## عرض المنتجات الغير موافق عليها للادمنز
     path('admin/products/', AdminProductListView.as_view(), name='admin-products-by-status'),
    path('approve/<int:product_id>/', 
         ProductApprovalView.as_view(), 
         name='product-approve'),
    path('disapprove/<int:product_id>/', 
         ProductDisapprovalView.as_view(), 
         name='product-disapprove'),
    path('', ProductListView.as_view(), name='product-list'),  # List all approved products
    path('seller/', SellerProductsByStatusView.as_view(), name='product-list-seller-status'),  # List all seller products by status
    path('<int:pk>/', ProductDetailView.as_view(), name='product-detail'),  # Single product
    path('category/<int:category_id>/products/', CategoryProductsView.as_view(), name='category-products'),
    path('category/<int:category_id>/top_products/', CategoryTopProductsView.as_view(), name='category-products'),
    path('search/', ProductSearchView.as_view(), name='product-search'),
    path('categories/parents/', ParentCategoryListView.as_view(), name='parent-categories'),
    path('categories/children/<int:parent_id>/', ChildCategoryListView.as_view(), name='child-categories'),
    path('update-quantity/<int:product_id>/', UpdateProductQuantityView.as_view(), name='update-product-quantity'),
    path('cart/', CartView.as_view(), name='cart'),
    path('cart/add/', AddToCartView.as_view(), name='add-to-cart'),
    path('cart/update/<int:item_id>/', UpdateCartItemView.as_view(), name='update-cart-item'),
    path('cart/remove/<int:item_id>/', RemoveFromCartView.as_view(), name='remove-from-cart'),
    path('wishlist/', WishlistView.as_view(), name='wishlist'),
    path('wishlist/add/', AddToWishlistView.as_view(), name='add-to-wishlist'),
    path('wishlist/remove/<int:item_id>/', RemoveFromWishlistView.as_view(), name='remove-from-wishlist'),
    path('wishlist/move-to-cart/<int:item_id>/', MoveToCartView.as_view(), name='move-to-cart'),
    path('sales/active/', ActiveSaleEventListView.as_view(), name='active-sales'),
    path('sales/<int:sale_id>/products/', ProductsInSaleView.as_view(), name='sale-products'),
    path('sales/<int:pk>/', SaleEventDetailView.as_view(), name='sale-detail'),
    path('sales/upcoming/', UpcomingSaleEventsView.as_view(), name='upcoming-sales'),
    # Admin endpoints
    path('admin/sales/create/', CreateSaleEventView.as_view(), name='create-sale'),
    # Seller endpoints
    path('seller/sales/', SellerProductSaleListView.as_view(), name='seller-sales'),
    path('seller/sales/add/', CreateProductSaleView.as_view(), name='add-product-to-sale'),
    path('seller/sales/update/', UpdateProductSaleView.as_view(), name='update-sale'),
    path('seller/sales/delete/', DeleteProductSaleView.as_view(), name='delete-sale'),
    path('discounts/<int:pk>/discount/',  ProductDiscountView.as_view(), name='product-discount'),
     path('discounts/detail/<int:product_id>/discount/', ProductDiscountDetailView.as_view(), name='product-discount-detail'),
    path('brands/', BrandListView.as_view(), name='brand-list'),                                   # GET approved brands
    path('brands/<int:pk>/', BrandDetailView.as_view(), name='brand-detail'),                      # GET single approved brand
    path('seller/brands/', SellerBrandsView.as_view(), name='seller-brands'),
    # Seller
    path('brands/my/', MyBrandRequestsView.as_view(), name='my-brand-requests'),                   # GET my brands (any status)
    path('brands/create/', BrandCreateView.as_view(), name='brand-create'),                        # POST create brand (pending)
    path('brands/<int:pk>/update/', BrandUpdateView.as_view(), name='brand-update'),               # PATCH (resets to pending)
    path('brands/<int:pk>/delete/', BrandDeleteView.as_view(), name='brand-delete'),               # DELETE (soft, if unused)

    # Admin
    path('brands/admin/pending/', AdminPendingBrandListView.as_view(), name='brand-admin-pending'),         # ?status=pending|rejected|approved
    path('brands/admin/<int:pk>/approve/', AdminApproveBrandView.as_view(), name='brand-admin-approve'),
    path('brands/admin/<int:pk>/reject/', AdminRejectBrandView.as_view(), name='brand-admin-reject'),

    # ---------- Blocking sellers ----------
    path('sellers/<int:seller_id>/block/', BlockSellerView.as_view(), name='block-seller'),
    path('sellers/blocked/', BlockedSellersListView.as_view(), name='list-blocked-sellers'),

    path('brands/<int:brand_id>/products/', BrandProductsView.as_view(), name='brand-products-by-id'),
    path('brands/slug/<slug:slug>/products/', BrandProductsView.as_view(), name='brand-products-by-slug'),
    
    path('brands/<int:brand_id>/block/', BlockBrandView.as_view(), name='brand-block'),      # POST to block, DELETE to unblock
    path('brands/blocked/', BlockedBrandsListView.as_view(), name='brand-blocked-list'),     # GET
    path('brands/<int:brand_id>/unblock/', UnblockBrandView.as_view(), name='brand-unblock'),
    path('brands/top-by-products/', TopBrandsByProductCountView.as_view(), name='top-brands-by-products'),
    
    ]


###...............
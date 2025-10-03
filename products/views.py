from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.forms import ValidationError
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from notifications.models import Notification
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from products.constants import BRAND_MIN_POINTS
from rest_framework.permissions import AllowAny

from accounts.permissionsUsers import (
    IsSuperAdmin, IsSeller, IsAdmin,
    IsSuperAdminOrAdmin, IsBuyerOrSeller
)

from .models import (
    Category, Product, ProductImage, WishlistItem,
    Wishlist, Cart, CartItem, SaleEvent, ProductSale,Brand, BrandStatus,BrandBlock,ProductEditRequest
)

from .permissions import IsSellerOrAdmin
from .serializers import (
    ProductSerializer, CartSerializer, CartItemSerializer,
    ProductLanguageSerializer, SaleEventSerializer,
    ProductSaleSerializer, WishlistItemSerializer,
    WishlistSerializer, CreateProductSaleSerializer,
    UpdateProductSaleSerializer, ProductDiscountSerializer,
    CategorySerializer,BrandSerializer, BrandCreateSerializer, 
    ProductBrandAssignSerializer,BrandReadSerializer,BrandUpdateSerializer,
    AdminBrandDecisionSerializer,ProductEditRequestSerializer,ProductEditRequestDetailSerializer
)

def exclude_blocked_brands(qs, request):
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        blocked_ids = BrandBlock.objects.filter(user=user).values_list('brand_id', flat=True)
        if blocked_ids:
            qs = qs.exclude(brand_id__in=blocked_ids)
    return qs

class BrandListView(generics.ListAPIView):
    queryset = Brand.objects.filter(is_active=True)
    serializer_class = BrandSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_authenticated:
            blocked_ids = BrandBlock.objects.filter(user=user).values_list('brand_id', flat=True)
            qs = qs.exclude(id__in=blocked_ids)
        return qs

class TopBrandsByProductCountView(APIView):
    permission_classes = []  # Public access
    
    def get(self, request):
        # Get top 5 brands with most products
        top_brands = Brand.objects.annotate(
            product_count=Count('products')
        ).filter(
            status=BrandStatus.APPROVED,
            is_active=True
        ).order_by('-product_count')[:5]  # Get top 5 only
        
        serializer = BrandSerializer(top_brands, many=True, context={'request': request})
        
        # Add product counts to the response
        response_data = []
        for brand, data in zip(top_brands, serializer.data):
            response_data.append({
                **data,
                'product_count': brand.product_count
            })
        
        return Response({
            'count': len(response_data),
            'results': response_data
        })

class MyBrandRequestsView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    def get(self, request):
        qs = Brand.objects.filter(owner=request.user, is_active=True).order_by('-created_at')
        return Response(BrandReadSerializer(qs, many=True).data)
    
class BrandCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def post(self, request):
        ser = BrandCreateSerializer(data=request.data, context={'request': request})
        if not ser.is_valid():
            return Response(ser.errors, status=400)
        brand = ser.save()
        # optional: notify admins there’s a new brand request
        try:
            Notification.objects.create(
                user=request.user,
                notification_type='brand_request_submitted',
                message_ar=f"تم إرسال طلب علامة تجارية: {brand.name}. بانتظار الموافقة.",
                message_en=f"Brand request submitted: {brand.name}. Awaiting approval.",
                content_object=brand
            )
        except Exception:
            pass
        return Response(BrandSerializer(brand).data, status=201)

class BrandApproveView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]  # or IsSuperAdminOrAdmin

    def post(self, request, brand_id):
        action = request.data.get('action')  # 'approve' / 'reject'
        brand = get_object_or_404(Brand, pk=brand_id, is_active=True)

        if action == 'approve':
            brand.status = BrandStatus.APPROVED
            brand.rejection_reason = None
            brand.approved_by = request.user
            brand.approved_at = timezone.now()
            brand.save()
            Notification.objects.create(
                user=brand.owner,
                notification_type='brand_approved',
                message_ar=f"تمت الموافقة على علامتك التجارية: {brand.name}.",
                message_en=f"Your brand has been approved: {brand.name}.",
                content_object=brand
            )
            return Response({'status': 'approved'})

        elif action == 'reject':
            reason = request.data.get('reason') or ""
            brand.status = BrandStatus.REJECTED
            brand.rejection_reason = reason
            brand.approved_by = None
            brand.approved_at = None
            brand.save()
            Notification.objects.create(
                user=brand.owner,
                notification_type='brand_rejected',
                message_ar=f"تم رفض طلب العلامة التجارية: {brand.name}.",
                message_en=f"Your brand request was rejected: {brand.name}.",
                content_object=brand
            )
            return Response({'status': 'rejected'})

        return Response({'error': 'action must be approve/reject'}, status=400)
     
class BrandUpdateView(generics.UpdateAPIView):
    queryset = Brand.objects.all()
    serializer_class = BrandUpdateSerializer
    permission_classes = [IsAuthenticated, IsSeller]

    def get_object(self):
        brand = get_object_or_404(Brand, pk=self.kwargs['pk'], owner=self.request.user, is_active=True)
        return brand

# Seller can delete their brand (only if safe). You can forbid deletion if products exist.
class BrandDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def delete(self, request, pk):
        brand = get_object_or_404(Brand, pk=pk, owner=request.user, is_active=True)
        # OPTIONAL: block delete if brand is in use by products
        from products.models import Product
        if Product.objects.filter(brand=brand).exists():
            return Response({"error": "Cannot delete a brand that is used by products."}, status=400)
        brand.is_active = False  # soft delete
        brand.save(update_fields=['is_active'])
        return Response(status=204)

# Admin: list unapproved/rejected/pending (usually pending for review)
class AdminPendingBrandListView(generics.ListAPIView):
    serializer_class = BrandReadSerializer
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]

    def get_queryset(self):
        show = self.request.query_params.get('status', 'pending')
        if show not in [BrandStatus.PENDING, BrandStatus.REJECTED, BrandStatus.APPROVED]:
            show = BrandStatus.PENDING
        return Brand.objects.filter(status=show, is_active=True).order_by('-updated_at')

# Admin approve
class AdminApproveBrandView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]

    def post(self, request, pk):
        brand = get_object_or_404(Brand, pk=pk, is_active=True)
        brand.status = BrandStatus.APPROVED
        brand.rejection_reason = None
        brand.approved_by = request.user
        brand.approved_at = timezone.now()
        brand.save()

        # notify owner
        Notification.objects.create(
            user=brand.owner,
            notification_type='brand_approved',
            message_ar=f"تمت الموافقة على العلامة التجارية: {brand.name}",
            message_en=f"Your brand has been approved: {brand.name}",
            content_object=brand,
        )
        return Response(BrandReadSerializer(brand).data, status=200)

# Admin reject
class AdminRejectBrandView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin] 

    def post(self, request, pk):
        brand = get_object_or_404(Brand, pk=pk, is_active=True)
        serializer = AdminBrandDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data['reason']
        brand.status = BrandStatus.REJECTED
        brand.rejection_reason = reason
        brand.approved_by = None
        brand.approved_at = None
        brand.save()

        # notify owner, who can now EDIT it (our update view sets status→pending)
        Notification.objects.create(
            user=brand.owner,
            notification_type='brand_rejected',
            message_ar=f"تم رفض العلامة التجارية: {brand.name}. السبب: {reason}",
            message_en=f"Your brand was rejected: {brand.name}. Reason: {reason}",
            content_object=brand,
        )
        return Response(BrandReadSerializer(brand).data, status=200)

class AssignBrandToProductView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def patch(self, request, product_id):
        product = get_object_or_404(Product, pk=product_id, seller=request.user)
        ser = ProductBrandAssignSerializer(product, data=request.data, partial=True, context={'request': request})
        if ser.is_valid():
            ser.save()
            return Response({'message': 'Brand assigned successfully', 'product_id': product.id})
        return Response(ser.errors, status=400)

class BrandDetailView(generics.RetrieveAPIView):
    serializer_class = BrandReadSerializer
    permission_classes = []
    queryset = Brand.objects.filter(is_active=True, status=BrandStatus.APPROVED)

    def get_serializer_context(self):
        return {'request': self.request}

class BrandProductsView(APIView):
    permission_classes = [AllowAny]  # public (for approved brands)

    def get(self, request, brand_id=None, slug=None):
        """
        List approved products for an approved brand.
        Access:
          - /api/product/brands/<int:brand_id>/products/
          - /api/product/brands/slug/<slug:slug>/products/
        """
        # language like elsewhere
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'

        # find the brand (must be approved [+ active if you use that field])
        if brand_id is not None:
            brand = get_object_or_404(
                Brand,
                pk=brand_id,
                status=BrandStatus.APPROVED,
                # is_active=True,  # uncomment if you have this field
            )
        else:
            brand = get_object_or_404(
                Brand,
                slug__iexact=slug,
                status=BrandStatus.APPROVED,
                # is_active=True,  # uncomment if you have this field
            )

        # if the user blocked this brand, don't show it
        if request.user.is_authenticated and BrandBlock.objects.filter(user=request.user, brand=brand).exists():
            # Option A (recommended): return empty list without leaking brand existence
            # return Response({"count": 0, "total_pages": 0, "current_page": 1, "next": None, "previous": None, "results": []})
            # Option B: pretend it doesn't exist
            raise Http404

        qs = Product.objects.filter(brand=brand, is_approved=True).order_by('-created_at')

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ProductLanguageSerializer(page, many=True, context={
            'lang': lang,
            'request': request,
            'show_discount_price': True
        })
        return paginator.get_paginated_response(serializer.data)

class BlockBrandView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, brand_id):
        brand = get_object_or_404(Brand, pk=brand_id, is_active=True)
        BrandBlock.objects.get_or_create(user=request.user, brand=brand)
        return Response({"message": "Brand blocked"}, status=201)

    def delete(self, request, brand_id):
        brand = get_object_or_404(Brand, pk=brand_id, is_active=True)
        BrandBlock.objects.filter(user=request.user, brand=brand).delete()
        return Response(status=204)

class UnblockBrandView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, brand_id):
        brand = get_object_or_404(Brand, pk=brand_id, is_active=True)
        BrandBlock.objects.filter(user=request.user, brand=brand).delete()
        return Response({"message": "Brand unblocked"}, status=200)

class BlockedBrandsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        brand_ids = BrandBlock.objects.filter(user=request.user).values_list('brand_id', flat=True)
        qs = Brand.objects.filter(id__in=brand_ids, is_active=True)
        return Response(BrandSerializer(qs, many=True).data)

class CreateCategoryView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request):
        name_ar = request.data.get('name_ar')
        name_en = request.data.get('name_en')
        parent_id = request.data.get('parent_id')
        logo = request.FILES.get('logo')  # Get the uploaded logo file

        if not name_ar or not name_en:
            return Response({'error': 'يجب إدخال الاسم بالعربي والإنجليزي.'}, status=400)

        # Check for duplicate names at the same level
        duplicate_filter = Q(name_ar__iexact=name_ar) | Q(name_en__iexact=name_en)
        if parent_id:
            duplicate_filter &= Q(parent_id=parent_id)
        else:
            duplicate_filter &= Q(parent__isnull=True)

        if Category.objects.filter(duplicate_filter).exists():
            return Response({'error': 'اسم الفئة موجود مسبقًا في هذا المستوى.'}, status=400)

        parent = None
        if parent_id:
            try:
                parent = Category.objects.get(pk=parent_id)
                
                # Prevent selecting a child category as parent
                if parent.parent:
                    return Response(
                        {'error': 'لا يمكن اختيار قسم فرعي كقسم رئيسي.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                    
            except Category.DoesNotExist:
                return Response({'error': 'الفئة الرئيسية غير موجودة.'}, status=404)

        # Create the category with logo if provided
        category_data = {
            'name_ar': name_ar,
            'name_en': name_en,
            'parent': parent
        }
        
        if logo:
            # Validate it's an image file
            if not logo.content_type.startswith('image/'):
                return Response({'error': 'يجب رفع ملف صورة فقط للشعار.'}, status=400)
            category_data['logo'] = logo

        category = Category.objects.create(**category_data)
        
        serializer = CategorySerializer(category, context={'request': request})
        return Response({
            'message': 'تم إنشاء الفئة بنجاح.',
            'category': serializer.data
        }, status=201)

class UpdateCategoryView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def put(self, request, pk):
        try:
            category = Category.objects.get(pk=pk)
        except Category.DoesNotExist:
            return Response({'error': 'الفئة غير موجودة.'}, status=404)

        name_ar = request.data.get('name_ar')
        name_en = request.data.get('name_en')
        parent_id = request.data.get('parent_id')

        if not name_ar or not name_en:
            return Response({'error': 'الاسم العربي والإنجليزي مطلوبان.'}, status=400)

        # Check for duplicate names at the same level
        duplicate_filter = (Q(name_ar__iexact=name_ar) | Q(name_en__iexact=name_en)) & ~Q(pk=pk)
        if parent_id:
            duplicate_filter &= Q(parent_id=parent_id)
        else:
            duplicate_filter &= Q(parent__isnull=True)

        if Category.objects.filter(duplicate_filter).exists():
            return Response({'error': 'اسم الفئة موجود مسبقًا في هذا المستوى.'}, status=400)

        # Prevent making a category its own parent
        if parent_id and int(parent_id) == pk:
            return Response({'error': 'لا يمكن جعل الفئة ابنة لنفسها.'}, status=400)

        # Prevent changing parent if category has children
        if category.children.exists() and parent_id and category.parent_id != int(parent_id):
            return Response({'error': 'لا يمكن تغيير المستوى لفئة لديها أقسام فرعية.'}, status=400)

        parent = None
        if parent_id:
            try:
                parent = Category.objects.get(pk=parent_id)
                
                # NEW VALIDATION: Prevent selecting a child category as parent
                if parent.parent:
                    return Response(
                        {'error': 'لا يمكن اختيار قسم فرعي كقسم رئيسي.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                    
                # NEW VALIDATION: Prevent circular relationships
                if self._is_circular_relationship(category, parent):
                    return Response(
                        {'error': 'لا يمكن إنشاء علاقة دائرية بين الأقسام.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                    
            except Category.DoesNotExist:
                return Response({'error': 'الفئة الرئيسية غير موجودة.'}, status=404)

        category.name_ar = name_ar
        category.name_en = name_en
        category.parent = parent
        category.save()

        return Response({'message': 'تم تحديث الفئة بنجاح.'})
    
    def _is_circular_relationship(self, category, potential_parent):
        """
        Check if assigning potential_parent as parent would create a circular relationship
        """
        # If the potential parent is already a child of this category
        current = potential_parent
        while current is not None:
            if current.id == category.id:
                return True
            current = current.parent
        return False
    
class DeleteCategoryView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def delete(self, request, pk):
        try:
            category = Category.objects.get(pk=pk)
            
            # Prevent deletion if category has children
            if category.children.exists():
                return Response({'error': 'لا يمكن حذف فئة لديها أقسام فرعية.'}, status=400)
                
            # Prevent deletion if category has products
            if category.products.exists():
                return Response({'error': 'لا يمكن حذف فئة تحتوي على منتجات.'}, status=400)
                
            category.delete()
            return Response({'message': 'تم حذف الفئة بنجاح.'})
        except Category.DoesNotExist:
            return Response({'error': 'الفئة غير موجودة.'}, status=404)

class LocalizedCategoryListView(APIView):
    permission_classes = []  # Accessible to everyone
    
    def get(self, request):
        language = request.headers.get('Accept-Language', 'ar').lower()
        if language not in ['ar', 'en']:
            language = 'ar'

        # Get all parent categories with their children
        parent_categories = Category.objects.filter(parent__isnull=True).prefetch_related('children')
        
        results = []
        for parent in parent_categories:
            parent_data = {
                'id': parent.id,
                'name': parent.name_ar if language == 'ar' else parent.name_en,
                'logo': request.build_absolute_uri(parent.logo.url) if parent.logo else None,
                'children': [],
            }
            
            for child in parent.children.all():
                parent_data['children'].append({
                    'id': child.id,
                    'name': child.name_ar if language == 'ar' else child.name_en,
                    'logo': request.build_absolute_uri(child.logo.url) if child.logo else None,
                })
            
            results.append(parent_data)

        return Response(results)

class ParentCategoryListView(APIView):
    permission_classes = []
    
    def get(self, request):
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        parent_categories = Category.objects.filter(parent__isnull=True)
        results = []
        
        for cat in parent_categories:
            results.append({
                'id': cat.id,
                'name': cat.name_ar if lang == 'ar' else cat.name_en,
                'has_children': cat.children.exists()
            })
        
        return Response(results)

class ChildCategoryListView(APIView):
    permission_classes = []
    
    def get(self, request, parent_id):
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        parent = get_object_or_404(Category, id=parent_id)
        children = parent.children.all()
        
        results = []
        for child in children:
            results.append({
                'id': child.id,
                'name': child.name_ar if lang == 'ar' else child.name_en
            })
        
        return Response(results)

class ProductCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def post(self, request, category_id):

        quantity = request.data.get('quantity', 1)  # Default to 1 if not provided

        try:
            quantity = int(quantity)
            if quantity < 0:
                return Response(
                    {"error": "Quantity must be a positive number"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid quantity value"},
                status=status.HTTP_400_BAD_REQUEST
            )


        # التحقق من وجود الفئة
        category = get_object_or_404(Category, id=category_id)
        
        # Changed from if not category.is_child:
        if not category.parent:  # This checks if it's a parent category
            return Response(
                {"error": "يجب اختيار قسم فرعي وليس رئيسي"},
                status=status.HTTP_400_BAD_REQUEST
            )


        # التحقق من المدخلات الأساسية
        name_ar = request.data.get('name_ar')
        name_en = request.data.get('name_en')
        description_ar = request.data.get('description_ar')
        description_en = request.data.get('description_en')
        price = request.data.get('price')
        images = request.FILES.getlist('images')
        brand_id = request.data.get('brand_id')
        brand = None
        if brand_id is not None and str(brand_id).strip() != "":
            try:
                brand = Brand.objects.get(pk=brand_id)
            except Brand.DoesNotExist:
                return Response({"error": "Brand not found"}, status=status.HTTP_404_NOT_FOUND)

            # must be approved
            if brand.status != BrandStatus.APPROVED:
                return Response({"error": "Brand is not approved yet"}, status=status.HTTP_400_BAD_REQUEST)

            # must be owned by this seller (or admin)
            if brand.owner != request.user and not request.user.is_staff:
                return Response({"error": "You do not own this brand"}, status=status.HTTP_403_FORBIDDEN)

            # (optional) double-gate by points/verified (you asked for it)
            if getattr(request.user, 'points', 0) < BRAND_MIN_POINTS and not getattr(request.user, 'is_verified_seller', False):
                return Response({"error": f"Minimum {BRAND_MIN_POINTS} points or verified seller required to use a brand"}, status=status.HTTP_403_FORBIDDEN)
            
        if not all([name_ar, name_en, description_ar, description_en, price]):
            return Response({"error": "جميع الحقول النصية مطلوبة"}, status=status.HTTP_400_BAD_REQUEST)

        if len(images) == 0:
            return Response({"error": "يجب رفع صورة واحدة على الأقل للمنتج"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            price = float(price)
            if price <= 0:
                return Response({"error": "يجب أن يكون السعر رقمًا موجبًا"}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({"error": "السعر يجب أن يكون رقمًا صحيحًا أو عشريًا"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                product = Product.objects.create(
                    category=category,
                    seller=request.user,
                    quantity=quantity,
                    name_ar=name_ar,
                    name_en=name_en,
                    description_ar=description_ar,
                    description_en=description_en,
                    price=price,
                    is_approved=False,
                    brand=brand
                )

                for image in images:
                    if not image.content_type.startswith('image/'):
                        raise ValidationError("يجب رفع ملفات صور فقط")
                    ProductImage.objects.create(product=product, image=image)

                serializer = ProductSerializer(product)
                return Response({
                    "message": "تم إنشاء المنتج بنجاح بانتظار الموافقة",
                    "product": serializer.data
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ProductApprovalView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]
    
    def post(self, request, product_id):
        """Approve a product"""
        product = get_object_or_404(Product, id=product_id)
        
        if product.is_approved:
            return Response(
                {"error": "Product is already approved"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        product.is_approved = True
        product.approved_by = request.user
        product.approved_at = timezone.now()
        product.status = 'approved'
        product.save()
        
                # Manually trigger notification if status changed
        if product.is_approved:
            from notifications.models import Notification
            Notification.objects.create(
                user=product.seller,
                notification_type='product_approved',
                message_ar=f"تمت الموافقة على منتجك: {product.name_ar}",
                message_en=f"Your product was approved: {product.name_en}",
                content_object=product
            )

        return Response(
            {"message": "Product approved successfully"},
            status=status.HTTP_200_OK
        )

class ProductDisapprovalView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]
    
    def post(self, request, product_id):
        """Disapprove a product with reason"""
        product = get_object_or_404(Product, id=product_id)
        reason_ar = request.data.get('reason_ar', '').strip()
        reason_en = request.data.get('reason_en', '').strip()

        if not reason_ar:
            return Response(
                {"error": "السبب مطلوب باللغة العربي reason_ar"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not reason_en:
            return Response(
                {"error": "the reason is requiered in english language reason_en"},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Store the old approval status to check if it changed
        was_approved = product.is_approved
        
        # Update product fields
        product.is_approved = False
        product.disapproval_reason_ar = reason_ar
        product.disapproval_reason_en = reason_en
        product.approved_by = request.user
        product.approved_at = timezone.now()
        product.status = 'rejected'
        product.save()
        
        # Manually trigger notification if status changed
        if was_approved != product.is_approved:
            from notifications.models import Notification
            Notification.objects.create(
                user=product.seller,
                notification_type='product_disapproved',
                message_ar=f"تم رفض منتجك: {product.name_ar}. السبب: {reason_ar}",
                message_en=f"Your product was rejected: {product.name_en}. Reason: {reason_en}",
                content_object=product,
                extra_data={'disapproval_reason': reason_ar}
            )
        
        return Response(
            {
                "message": "Product disapproved",
                "reason": reason_ar
            },
            status=status.HTTP_200_OK
        )

# products/views.py
class SellerProductsByStatusView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def get(self, request):
        """
        Get seller's products filtered by status with search, pagination, and sorting
        Query parameters: 
        - status: pending|approved|rejected
        - search: search query
        - page: page number
        - page_size: items per page (default: 20)
        - sort_by: created_at (default) or updated_at
        - sort_order: asc or desc (default: desc)
        """
        # Get query parameters
        status_filter = request.query_params.get('status', '').lower()
        search_query = request.query_params.get('search', '').strip()
        page_number = request.query_params.get('page', 1)
        page_size = request.query_params.get('page_size', 20)
        sort_by = request.query_params.get('sort_by', 'created_at')
        sort_order = request.query_params.get('sort_order', 'desc')
        
        # Get language from headers
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        # Base queryset - only products belonging to the seller
        products = Product.objects.filter(seller=request.user)
        
        # Apply status filter if provided and valid
        valid_statuses = ['pending', 'approved', 'rejected']
        if status_filter and status_filter in valid_statuses:
            products = products.filter(status=status_filter)
        
        # Apply search filter if provided
        if search_query:
            products = products.filter(
                Q(name_ar__icontains=search_query) |
                Q(name_en__icontains=search_query) |
                Q(description_ar__icontains=search_query) |
                Q(description_en__icontains=search_query) |
                Q(brand__name__icontains=search_query) |
                Q(category__name_ar__icontains=search_query) |
                Q(category__name_en__icontains=search_query)
            )
        
        # Validate and apply sorting
        valid_sort_fields = ['created_at', 'updated_at']
        if sort_by not in valid_sort_fields:
            sort_by = 'created_at'
        
        sort_order = sort_order.lower()
        if sort_order not in ['asc', 'desc']:
            sort_order = 'desc'
        
        sort_prefix = '' if sort_order == 'asc' else '-'
        sort_param = f"{sort_prefix}{sort_by}"
        
        products = products.order_by(sort_param)
        
        # Apply pagination
        try:
            page_number = int(page_number)
            if page_number < 1:
                page_number = 1
        except (ValueError, TypeError):
            page_number = 1
        
        try:
            page_size = int(page_size)
            if page_size < 1:
                page_size = 20
            elif page_size > 100:  # Limit page size to prevent abuse
                page_size = 100
        except (ValueError, TypeError):
            page_size = 20
        
        paginator = PageNumberPagination()
        paginator.page_size = page_size
        paginated_products = paginator.paginate_queryset(products, request)
        
        # Use the existing serializer with language context
        serializer = ProductLanguageSerializer(paginated_products, many=True, context={
            'lang': lang,
            'request': request,
            'show_discount_details': True
        })
        
        # Add counts for each status (including search filter if applicable)
        base_queryset = Product.objects.filter(seller=request.user)
        
        if search_query:
            search_filtered = base_queryset.filter(
                Q(name_ar__icontains=search_query) |
                Q(name_en__icontains=search_query) |
                Q(description_ar__icontains=search_query) |
                Q(description_en__icontains=search_query) |
                Q(brand__name__icontains=search_query) |
                Q(category__name_ar__icontains=search_query) |
                Q(category__name_en__icontains=search_query)
            )
            status_counts = {
                'pending': search_filtered.filter(status='pending').count(),
                'approved': search_filtered.filter(status='approved').count(),
                'rejected': search_filtered.filter(status='rejected').count(),
                'total': search_filtered.count()
            }
        else:
            status_counts = {
                'pending': base_queryset.filter(status='pending').count(),
                'approved': base_queryset.filter(status='approved').count(),
                'rejected': base_queryset.filter(status='rejected').count(),
                'total': base_queryset.count()
            }
        
        # Build the next page URL
        next_page_url = None
        if paginator.page.has_next():
            next_page_number = paginator.page.next_page_number()
            next_page_url = self._build_page_url(request, next_page_number, {
                'status': status_filter,
                'search': search_query,
                'page_size': page_size,
                'sort_by': sort_by,
                'sort_order': sort_order
            })
        
        # Build the previous page URL
        previous_page_url = None
        if paginator.page.has_previous():
            previous_page_number = paginator.page.previous_page_number()
            previous_page_url = self._build_page_url(request, previous_page_number, {
                'status': status_filter,
                'search': search_query,
                'page_size': page_size,
                'sort_by': sort_by,
                'sort_order': sort_order
            })
        
        # Build response with pagination metadata
        response_data = {
            'status_filter': status_filter if status_filter else 'all',
            'search_query': search_query if search_query else None,
            'sorting': {
                'by': sort_by,
                'order': sort_order
            },
            'pagination': {
                'current_page': paginator.page.number,
                'page_size': page_size,
                'total_pages': paginator.page.paginator.num_pages,
                'total_items': paginator.page.paginator.count,
                'has_next': paginator.page.has_next(),
                'has_previous': paginator.page.has_previous(),
                'next_page_number': paginator.page.next_page_number() if paginator.page.has_next() else None,
                'previous_page_number': paginator.page.previous_page_number() if paginator.page.has_previous() else None,
                'next_page_url': next_page_url,
                'previous_page_url': previous_page_url,
            },
            'counts': status_counts,
            'products': serializer.data
        }
        
        return Response(response_data)
    
    def _build_page_url(self, request, page_number, params):
        """
        Build a URL for a specific page with all the current query parameters
        """
        # Get the base URL
        base_url = request.build_absolute_uri().split('?')[0]
        
        # Build query parameters
        query_params = []
        
        # Add page number
        query_params.append(f'page={page_number}')
        
        # Add other parameters if they exist
        if params.get('status'):
            query_params.append(f'status={params["status"]}')
        
        if params.get('search'):
            query_params.append(f'search={params["search"]}')
        
        if params.get('page_size'):
            query_params.append(f'page_size={params["page_size"]}')
        
        if params.get('sort_by'):
            query_params.append(f'sort_by={params["sort_by"]}')
        
        if params.get('sort_order'):
            query_params.append(f'sort_order={params["sort_order"]}')
        
        # Combine all parameters
        if query_params:
            return f"{base_url}?{'&'.join(query_params)}"
        
        return f"{base_url}?page={page_number}"

class SellerUnapprovedProductsView(APIView): 
    permission_classes = [IsAuthenticated, IsSeller]
    
    def get(self, request):
        # الحصول على اللغة من الهيدر مع جعل العربية الافتراضية
        lang = request.headers.get('Accept-Language', 'ar').lower()
        
        # إذا كانت اللغة غير معروفة أو غير مدعومة، نستخدم العربية
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        # الحصول على منتجات البائع غير الموافق عليها مع معلومات الفئة
        products = Product.objects.filter(
            seller=request.user,
            is_approved=False,
        ).select_related('category').prefetch_related('images')
        
        # استخدام السيريالايزر مع تحديد اللغة
        serializer = ProductLanguageSerializer(products, many=True, context={'lang': lang})
        return Response(serializer.data)    

class SellerApprovedProductsView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def get(self, request):
        # الحصول على اللغة من الهيدر مع جعل العربية الافتراضية
        lang = request.headers.get('Accept-Language', 'ar').lower()
        
        # التحقق من اللغات المدعومة (العربية والإنجليزية فقط)
        if lang not in ['ar', 'en']:
            lang = 'ar'  # نستخدم العربية إذا كانت اللغة غير معروفة
        
        # الحصول على منتجات البائع الموافق عليها مع تحسين الأداء
        products = Product.objects.filter(
            seller=request.user,
            is_approved=True,
        ).select_related('category').prefetch_related('images')
        
        # استخدام السيريالايزر مع تحديد اللغة
        serializer = ProductLanguageSerializer(products, many=True, context={
            'lang': lang,
            'request': request,
            'show_discount_details': True  # Show full discount info for seller
        })
        return Response(serializer.data)
    
class SellerProductDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def delete(self, request, product_id):
        # الحصول على المنتج والتأكد من أنه ملك للبائع
        product = get_object_or_404(Product, id=product_id)
        
        if product.seller != request.user:
            return Response(
                {"error": "ليس لديك صلاحية حذف هذا المنتج"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        product.delete()
        return Response(
            {"message": "تم حذف المنتج بنجاح"},
            status=status.HTTP_204_NO_CONTENT
        )    

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    
    def paginate_queryset(self, queryset, request, view=None):
        """
        Add page number validation and total pages count
        """
        self.request = request  # Store the request object for link generation
        page_size = self.get_page_size(request)
        paginator = self.django_paginator_class(queryset, page_size)
        page_number = request.query_params.get(self.page_query_param, 1)
        
        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            raise NotFound("Invalid page number. Please provide a positive integer.")
            
        if page_number < 1:
            raise NotFound("Invalid page number. Pages start from 1.")
            
        try:
            self.page = paginator.page(page_number)
        except:
            raise NotFound("Invalid page number. Page does not exist.")
            
        self.total_pages = paginator.num_pages
        return list(self.page)
    
    def get_paginated_response(self, data):
        """
        Include total pages in response with proper request context for links
        """
        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.total_pages,
            'current_page': self.page.number,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data
        })

class ProductListView(APIView):
    permission_classes = []  # Accessible to anyone
    
    def get(self, request):
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        # Get all filter parameters
        min_price = request.query_params.get('min_price')
        max_price = request.query_params.get('max_price')
        min_rating = request.query_params.get('min_rating')
        max_rating = request.query_params.get('max_rating')
        category_id = request.query_params.get('category_id')
        parent_category_id = request.query_params.get('parent_category_id')
        min_quantity = request.query_params.get('min_quantity')
        max_quantity = request.query_params.get('max_quantity')
        in_stock = request.query_params.get('in_stock')
        has_discount = request.query_params.get('has_discount')
        brand_id = request.query_params.get('brand_id')
        brand_slug = request.query_params.get('brand_slug')
        brand_name = request.query_params.get('brand_name')
        # Get sorting parameters
        sort_by = request.query_params.get('sort_by', '-created_at')  # Default: newest first
        sort_direction = request.query_params.get('sort_direction', 'desc')  # Default: descending
        
        # Validate sort options
        valid_sort_fields = ['price', 'created_at', 'rating']
        if sort_by not in valid_sort_fields:
            sort_by = 'created_at'
        
        # Validate sort direction
        sort_direction = sort_direction.lower()
        if sort_direction not in ['asc', 'desc']:
            sort_direction = 'desc'
        
        # Build sort parameter
        sort_prefix = '' if sort_direction == 'asc' else '-'
        sort_param = f"{sort_prefix}{sort_by}"
        
        # Start with base queryset
        products = Product.objects.filter(is_approved=True)
        
        # Apply category filters
        if category_id:
            products = products.filter(category_id=category_id)
        elif parent_category_id:
            products = products.filter(category__parent_id=parent_category_id)
        
        # Apply price filters
        if min_price:
            try:
                products = products.filter(price__gte=float(min_price))
            except (ValueError, TypeError):
                pass
                
        if max_price:
            try:
                products = products.filter(price__lte=float(max_price))
            except (ValueError, TypeError):
                pass
        
        # Apply rating filters
        if min_rating:
            try:
                products = products.filter(rating__gte=float(min_rating))
            except (ValueError, TypeError):
                pass
                
        if max_rating:
            try:
                products = products.filter(rating__lte=float(max_rating))
            except (ValueError, TypeError):
                pass

        # Apply quantity filters
        if min_quantity:
            try:
                products = products.filter(quantity__gte=int(min_quantity))
            except (ValueError, TypeError):
                pass
                
        if max_quantity:
            try:
                products = products.filter(quantity__lte=int(max_quantity))
            except (ValueError, TypeError):
                pass
                
        # Apply in-stock filter
        if in_stock and in_stock.lower() in ['true', '1', 'yes']:
            products = products.filter(quantity__gt=0)

        # Apply discount filter
        if has_discount and has_discount.lower() in ['true', '1', 'yes']:
            now = timezone.now()
            products = products.filter(
                Q(has_standalone_discount=True) &
                Q(standalone_discount_percentage__isnull=False) &
                (
                    Q(standalone_discount_start__isnull=True) | 
                    Q(standalone_discount_start__lte=now)
                ) &
                (
                    Q(standalone_discount_end__isnull=True) | 
                    Q(standalone_discount_end__gte=now)
                )
            )
        
        if brand_id:
            try:
                products = products.filter(brand_id=int(brand_id))
            except (TypeError, ValueError):
                pass

        if brand_slug:
            products = products.filter(brand__slug__iexact=brand_slug)

        if brand_name:
            products = products.filter(brand__name__icontains=brand_name)
        
        # Apply sorting
        products = products.order_by(sort_param)
        products = exclude_blocked_brands(products, request)
        # Pagination with proper request context
        paginator = StandardResultsSetPagination()
        result_page = paginator.paginate_queryset(products, request)
        
        serializer = ProductLanguageSerializer(result_page, many=True, context={
            'lang': lang,
            'request': request,
            'show_discount_price': True
        })
        
        return paginator.get_paginated_response(serializer.data)

class AdminProductListView(APIView):
    permission_classes = [IsAuthenticated,IsSuperAdmin]  # Accessible to admins only
    
    def get(self, request):
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        # Get all filter parameters
        min_price = request.query_params.get('min_price')
        max_price = request.query_params.get('max_price')
        min_rating = request.query_params.get('min_rating')
        max_rating = request.query_params.get('max_rating')
        category_id = request.query_params.get('category_id')
        parent_category_id = request.query_params.get('parent_category_id')
        min_quantity = request.query_params.get('min_quantity')
        max_quantity = request.query_params.get('max_quantity')
        in_stock = request.query_params.get('in_stock')
        status_filter = request.query_params.get('status', '').lower()
        has_discount = request.query_params.get('has_discount')
        brand_id = request.query_params.get('brand_id')
        brand_slug = request.query_params.get('brand_slug')
        brand_name = request.query_params.get('brand_name')
        # Get sorting parameters
        sort_by = request.query_params.get('sort_by', '-created_at')  # Default: newest first
        sort_direction = request.query_params.get('sort_direction', 'desc')  # Default: descending
        
        # Validate sort options
        valid_sort_fields = ['price', 'created_at', 'rating']
        if sort_by not in valid_sort_fields:
            sort_by = 'created_at'
        
        # Validate sort direction
        sort_direction = sort_direction.lower()
        if sort_direction not in ['asc', 'desc']:
            sort_direction = 'desc'
        
        # Build sort parameter
        sort_prefix = '' if sort_direction == 'asc' else '-'
        sort_param = f"{sort_prefix}{sort_by}"
        
        # Start with base queryset
        products = Product.objects.filter(is_approved=True)
        
        # Apply category filters
        if category_id:
            products = products.filter(category_id=category_id)
        elif parent_category_id:
            products = products.filter(category__parent_id=parent_category_id)
        
        valid_statuses = ['pending', 'approved', 'rejected']
        if status_filter and status_filter in valid_statuses:
            products = products.filter(status=status_filter)

        # Apply price filters
        if min_price:
            try:
                products = products.filter(price__gte=float(min_price))
            except (ValueError, TypeError):
                pass
                
        if max_price:
            try:
                products = products.filter(price__lte=float(max_price))
            except (ValueError, TypeError):
                pass
        
        # Apply rating filters
        if min_rating:
            try:
                products = products.filter(rating__gte=float(min_rating))
            except (ValueError, TypeError):
                pass
                
        if max_rating:
            try:
                products = products.filter(rating__lte=float(max_rating))
            except (ValueError, TypeError):
                pass

        # Apply quantity filters
        if min_quantity:
            try:
                products = products.filter(quantity__gte=int(min_quantity))
            except (ValueError, TypeError):
                pass
                
        if max_quantity:
            try:
                products = products.filter(quantity__lte=int(max_quantity))
            except (ValueError, TypeError):
                pass
                
        # Apply in-stock filter
        if in_stock and in_stock.lower() in ['true', '1', 'yes']:
            products = products.filter(quantity__gt=0)

        # Apply discount filter
        if has_discount and has_discount.lower() in ['true', '1', 'yes']:
            now = timezone.now()
            products = products.filter(
                Q(has_standalone_discount=True) &
                Q(standalone_discount_percentage__isnull=False) &
                (
                    Q(standalone_discount_start__isnull=True) | 
                    Q(standalone_discount_start__lte=now)
                ) &
                (
                    Q(standalone_discount_end__isnull=True) | 
                    Q(standalone_discount_end__gte=now)
                )
            )
        
        if brand_id:
            try:
                products = products.filter(brand_id=int(brand_id))
            except (TypeError, ValueError):
                pass

        if brand_slug:
            products = products.filter(brand__slug__iexact=brand_slug)

        if brand_name:
            products = products.filter(brand__name__icontains=brand_name)
        
        # Apply sorting
        products = products.order_by(sort_param)
        products = exclude_blocked_brands(products, request)
        # Pagination with proper request context
        paginator = StandardResultsSetPagination()
        result_page = paginator.paginate_queryset(products, request)
        
        serializer = ProductLanguageSerializer(result_page, many=True, context={
            'lang': lang,
            'request': request,
            'show_discount_price': True
        })
        
        return paginator.get_paginated_response(serializer.data)

class SellerSimplifiedApprovedProductsListView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def get(self, request):
        """
        Get ID, name_ar, name_en, and one image of seller's approved products
        For use in product selection with preview
        """
        # Get approved products with prefetch for images to optimize performance
        products = Product.objects.filter(
            seller=request.user,
            is_approved=True,
            status='approved'
        ).prefetch_related('images').order_by('name_ar')
        
        # Prepare the response data with one image
        products_data = []
        for product in products:
            # Get the first image if available
            first_image = None
            if product.images.exists():
                first_image_obj = product.images.first()
                first_image = request.build_absolute_uri(first_image_obj.image.url)
            
            products_data.append({
                'id': product.id,
                'name_ar': product.name_ar,
                'name_en': product.name_en,
                'image': first_image  # Will be null if no images
            })
        
        return Response({
            'count': len(products_data),
            'products': products_data
        })

class SellerSalesParticipationView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def get(self, request):
        """
        Get all sales that the seller has products in, with product details
        """
        # Get all product sales where the product belongs to the current seller
        product_sales = ProductSale.objects.filter(
            product__seller=request.user
        ).select_related('sale_event', 'product').prefetch_related('product__images')
        
        # Organize by sale event
        sales_data = {}
        for ps in product_sales:
            sale_event = ps.sale_event
            product = ps.product
            
            # Get product image
            product_image = None
            if product.images.exists():
                first_image = product.images.first()
                product_image = request.build_absolute_uri(first_image.image.url)
            
            # Calculate prices
            original_price = float(product.price)
            discount_percentage = float(ps.discount_percentage)
            current_price = original_price * (1 - discount_percentage / 100)
            
            product_info = {
                'product_id': product.id,
                'product_name_ar': product.name_ar,
                'product_name_en': product.name_en,
                'product_image': product_image,
                'original_price': original_price,
                'current_price': round(current_price, 2),
                'discount_percentage': discount_percentage,
                'sale_start_date': sale_event.start_date,
                'sale_end_date': sale_event.end_date
            }
            
            # Add to sales data organized by sale event
            if sale_event.id not in sales_data:
                # Get sale event image
                sale_image = None
                if sale_event.image:
                    sale_image = request.build_absolute_uri(sale_event.image.url)
                
                sales_data[sale_event.id] = {
                    'sale_id': sale_event.id,
                    'sale_name_ar': sale_event.name_ar,
                    'sale_name_en': sale_event.name_en,
                    'sale_image': sale_image,
                    'sale_start_date': sale_event.start_date,
                    'sale_end_date': sale_event.end_date,
                    'sale_status': self._get_sale_status(sale_event),
                    'products': []
                }
            
            sales_data[sale_event.id]['products'].append(product_info)
        
        # Convert to list and sort by sale start date (newest first)
        sales_list = list(sales_data.values())
        sales_list.sort(key=lambda x: x['sale_start_date'], reverse=True)
        
        return Response({
            'count': len(sales_list),
            'sales': sales_list
        })
    
    def _get_sale_status(self, sale_event):
        """Determine sale status based on current time"""
        now = timezone.now()
        if sale_event.start_date > now:
            return 'upcoming'
        elif sale_event.end_date < now:
            return 'ended'
        else:
            return 'active'

class ProductEditRequestView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def post(self, request, product_id):
        """
        Create a new edit request for a product
        """
        product = get_object_or_404(Product, id=product_id, seller=request.user)
        
        # Check if there's already a pending edit request for this product
        pending_request = ProductEditRequest.objects.filter(
            product=product, 
            status=ProductEditRequest.PENDING
        ).first()
        
        if pending_request:
            return Response(
                {"error": "There's already a pending edit request for this product"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Don't copy the entire request.data - handle files separately
        # Create a mutable copy of the POST data (excluding files)
        data = request.POST.dict().copy() if request.POST else {}
        
        # Handle files separately
        files = request.FILES
        
        # Prepare data for serializer
        serializer_data = {
            'product': product.id,
            # Add other fields from the request
        }
        
        # Add text fields if they exist
        for field in ['name_ar', 'name_en', 'description_ar', 'description_en', 
                    'price', 'category', 'brand', 'quantity']:
            if field in data:
                serializer_data[field] = data[field]
        
        # Handle files
        if 'new_images' in files:
            serializer_data['new_images'] = files.getlist('new_images')
        
        serializer = ProductEditRequestSerializer(
            data=serializer_data, 
            context={'request': request}
        )
        
        if serializer.is_valid():
            edit_request = serializer.save()
            
            # Set product to pending approval
            product.is_approved = False
            product.status = 'pending'
            product.save()
            
            # Notify admins about the edit request
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                
                admin_users = User.objects.filter(
                    Q(role='admin') | Q(role='super_admin') | Q(is_staff=True)
                )
                
                for admin in admin_users:
                    Notification.objects.create(
                        user=admin,
                        notification_type='product_edit_request',
                        message_ar=f"طلب تعديل جديد للمنتج: {product.name_ar} من قبل البائع: {request.user.username}",
                        message_en=f"New edit request for product: {product.name_en} by seller: {request.user.username}",
                        content_object=edit_request
                    )
            except Exception:
                pass
            
            return Response(
                ProductEditRequestDetailSerializer(edit_request, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SellerEditRequestsView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def get(self, request):
        """
        Get all edit requests for the current seller
        """
        status_filter = request.query_params.get('status', '')
        
        edit_requests = ProductEditRequest.objects.filter(seller=request.user)
        
        if status_filter:
            edit_requests = edit_requests.filter(status=status_filter)
        
        edit_requests = edit_requests.order_by('-created_at')
        
        serializer = ProductEditRequestDetailSerializer(
            edit_requests, 
            many=True, 
            context={'request': request}
        )
        
        return Response(serializer.data)

class EditRequestDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def get(self, request, request_id):
        """
        Get details of a specific edit request
        """
        edit_request = get_object_or_404(
            ProductEditRequest, 
            id=request_id, 
            seller=request.user
        )
        
        serializer = ProductEditRequestDetailSerializer(
            edit_request, 
            context={'request': request}
        )
        
        return Response(serializer.data)

class AdminEditRequestsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]
    
    def get(self, request):
        """
        Get all edit requests for admin review
        """
        status_filter = request.query_params.get('status', ProductEditRequest.PENDING)
        
        edit_requests = ProductEditRequest.objects.filter(status=status_filter)
        edit_requests = edit_requests.order_by('-created_at')
        
        serializer = ProductEditRequestDetailSerializer(
            edit_requests, 
            many=True, 
            context={'request': request}
        )
        
        return Response(serializer.data)

class SellerBrandsView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def get(self, request):
        """
        Get all brands belonging to the current seller
        Query parameters: 
        - status: Filter by status (pending, approved, rejected)
        - page: Page number
        - page_size: Items per page
        """
        # Get query parameters
        status_filter = request.query_params.get('status', '').lower()
        page_number = request.query_params.get('page', 1)
        page_size = request.query_params.get('page_size', 20)
        
        # Base queryset - only brands belonging to the seller
        brands = Brand.objects.filter(owner=request.user, is_active=True)
        
        # Apply status filter if provided and valid
        valid_statuses = ['pending', 'approved', 'rejected']
        if status_filter and status_filter in valid_statuses:
            brands = brands.filter(status=status_filter)
        
        # Order by creation date (newest first)
        brands = brands.order_by('-created_at')
        
        # Apply pagination
        try:
            page_number = int(page_number)
            if page_number < 1:
                page_number = 1
        except (ValueError, TypeError):
            page_number = 1
        
        try:
            page_size = int(page_size)
            if page_size < 1:
                page_size = 20
            elif page_size > 100:
                page_size = 100
        except (ValueError, TypeError):
            page_size = 20
        
        paginator = PageNumberPagination()
        paginator.page_size = page_size
        paginated_brands = paginator.paginate_queryset(brands, request)
        
        # Serialize the brands
        serializer = BrandReadSerializer(
            paginated_brands, 
            many=True, 
            context={'request': request}
        )
        
        # Add counts for each status
        status_counts = {
            'pending': Brand.objects.filter(owner=request.user, status='pending', is_active=True).count(),
            'approved': Brand.objects.filter(owner=request.user, status='approved', is_active=True).count(),
            'rejected': Brand.objects.filter(owner=request.user, status='rejected', is_active=True).count(),
            'total': Brand.objects.filter(owner=request.user, is_active=True).count()
        }
        
        # Build response with pagination metadata
        response_data = {
            'status_filter': status_filter if status_filter else 'all',
            'pagination': {
                'current_page': paginator.page.number,
                'page_size': page_size,
                'total_pages': paginator.page.paginator.num_pages,
                'total_items': paginator.page.paginator.count,
                'has_next': paginator.page.has_next(),
                'has_previous': paginator.page.has_previous(),
            },
            'counts': status_counts,
            'brands': serializer.data
        }
        
        return Response(response_data)

class AdminApproveEditRequestView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]
    
    def post(self, request, request_id):
        """
        Approve an edit request and update the product
        """
        edit_request = get_object_or_404(ProductEditRequest, id=request_id)
        
        # Update the product with the edited fields
        product = edit_request.product
        
        # Update only the fields that were provided in the edit request
        if edit_request.name_ar is not None:
            product.name_ar = edit_request.name_ar
        if edit_request.name_en is not None:
            product.name_en = edit_request.name_en
        if edit_request.description_ar is not None:
            product.description_ar = edit_request.description_ar
        if edit_request.description_en is not None:
            product.description_en = edit_request.description_en
        if edit_request.price is not None:
            product.price = edit_request.price
        if edit_request.category is not None:
            product.category = edit_request.category
        if edit_request.brand is not None:
            product.brand = edit_request.brand
        if edit_request.quantity is not None:
            product.quantity = edit_request.quantity
        
        # Handle new images if any
        if edit_request.new_images.exists():
            # Remove old images
            product.images.all().delete()
            
            # Add new images
            for edit_image in edit_request.new_images.all():
                ProductImage.objects.create(product=product, image=edit_image.image)
        
        # Set product as approved
        product.is_approved = True
        product.status = 'approved'
        product.approved_by = request.user
        product.approved_at = timezone.now()
        product.save()
        
        # Update edit request status
        edit_request.status = ProductEditRequest.APPROVED
        edit_request.save()
        
        # Notify the seller
        try:
            Notification.objects.create(
                user=edit_request.seller,
                notification_type='product_edit_approved',
                message_ar=f"تمت الموافقة على تعديلات المنتج: {product.name_ar}",
                message_en=f"Your edits for product: {product.name_en} have been approved",
                content_object=product
            )
        except Exception:
            pass
        
        return Response({
            "message": "Edit request approved and product updated successfully",
            "product": ProductSerializer(product, context={'request': request}).data
        })

class AdminRejectEditRequestView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]
    
    def post(self, request, request_id):
        """
        Reject an edit request
        """
        edit_request = get_object_or_404(ProductEditRequest, id=request_id)
        rejection_reason = request.data.get('rejection_reason', '')
        
        if not rejection_reason:
            return Response(
                {"error": "Rejection reason is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update edit request status
        edit_request.status = ProductEditRequest.REJECTED
        edit_request.rejection_reason = rejection_reason
        edit_request.save()
        
        # Set product back to approved (since edits were rejected)
        product = edit_request.product
        product.is_approved = True
        product.status = 'approved'
        product.save()
        
        # Notify the seller
        try:
            Notification.objects.create(
                user=edit_request.seller,
                notification_type='product_edit_rejected',
                message_ar=f"تم رفض تعديلات المنتج: {product.name_ar}. السبب: {rejection_reason}",
                message_en=f"Your edits for product: {product.name_en} were rejected. Reason: {rejection_reason}",
                content_object=product
            )
        except Exception:
            pass
        
        return Response({
            "message": "Edit request rejected",
            "rejection_reason": rejection_reason
        })

class ProductDiscountDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def get(self, request, product_id):
        """
        Get detailed discount information for a specific product
        URL: /product/discounts/${productId}/discount/
        """
        # Get the product and verify ownership
        product = get_object_or_404(
            Product, 
            id=product_id, 
            seller=request.user,
        )
        
        # Check if product has active standalone discount
        has_active_discount = False
        current_time = timezone.now()
        
        if (product.has_standalone_discount and 
            product.standalone_discount_percentage is not None):
            
            # Check if discount is within valid time range (if dates are set)
            start_valid = (product.standalone_discount_start is None or 
                          product.standalone_discount_start <= current_time)
            end_valid = (product.standalone_discount_end is None or 
                        product.standalone_discount_end >= current_time)
            
            has_active_discount = start_valid and end_valid
        
        # Calculate current price with discount
        product_current_price = product.price
        if has_active_discount and product.standalone_discount_percentage:
            discount_amount = (product.price * product.standalone_discount_percentage) / 100
            product_current_price = product.price - discount_amount
        
        # Prepare response data matching your interface
        discount_data = {
            'id': product.id,
            'product_id': product.id,
            'product_name': product.name_ar if request.headers.get('Accept-Language', 'ar').lower() == 'ar' else product.name_en,
            'product_price': float(product.price),
            'product_current_price': float(product_current_price),
            'has_active_discount': has_active_discount,
            'has_standalone_discount': product.has_standalone_discount,
            'standalone_discount_percentage': float(product.standalone_discount_percentage) if product.standalone_discount_percentage else None,
            'standalone_discount_start': product.standalone_discount_start.isoformat() if product.standalone_discount_start else None,
            'standalone_discount_end': product.standalone_discount_end.isoformat() if product.standalone_discount_end else None,
            'created_at': product.created_at.isoformat(),
            'updated_at': product.updated_at.isoformat()
        }
        
        return Response(discount_data, status=status.HTTP_200_OK)

class AdminProductsByStatusView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]
    
    def get(self, request):
        """
        Get all products filtered by status for admin
        Query parameter: ?status=pending|approved|rejected
        If no status provided, returns all products
        """
        # Get status from query parameters
        status_filter = request.query_params.get('status', '').lower()
        
        # Get language from headers
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        # Base queryset - all products for admin
        products = Product.objects.all()
        
        # Apply status filter if provided and valid
        valid_statuses = ['pending', 'approved', 'rejected']
        if status_filter and status_filter in valid_statuses:
            products = products.filter(status=status_filter)
        
        # Apply additional filters if needed
        seller_id = request.query_params.get('seller_id')
        if seller_id:
            try:
                products = products.filter(seller_id=int(seller_id))
            except (ValueError, TypeError):
                pass
        
        category_id = request.query_params.get('category_id')
        if category_id:
            try:
                products = products.filter(category_id=int(category_id))
            except (ValueError, TypeError):
                pass
        
        # Order by creation date (newest first)
        products = products.order_by('-created_at')
        
        # Apply pagination
        paginator = StandardResultsSetPagination()
        result_page = paginator.paginate_queryset(products, request)
        
        # Use the existing serializer with language context
        serializer = ProductLanguageSerializer(result_page, many=True, context={
            'lang': lang,
            'request': request,
            'show_discount_details': True,
            'show_admin_details': True  # Add this to show admin-specific details
        })
        
        # Add counts for each status
        status_counts = {
            'pending': Product.objects.filter(status='pending').count(),
            'approved': Product.objects.filter(status='approved').count(),
            'rejected': Product.objects.filter(status='rejected').count(),
            'total': Product.objects.count()
        }
        
        # Get response data with pagination
        response_data = paginator.get_paginated_response(serializer.data).data
        
        # Add additional information
        response_data.update({
            'status_filter': status_filter if status_filter else 'all',
            'counts': status_counts,
            'current_filters': {
                'status': status_filter,
                'seller_id': seller_id,
                'category_id': category_id
            }
        })
        
        return Response(response_data)

class ProductDetailView(APIView):
    permission_classes = []  # Accessible to anyone
    
    def get(self, request, pk):
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
            
        product = get_object_or_404(Product, pk=pk, is_approved=True)
        
        # Check if user has blocked this brand
        if request.user.is_authenticated and product.brand_id:
            if BrandBlock.objects.filter(user=request.user, brand_id=product.brand_id).exists():
                raise Http404
        
        # Get basic product data
        product_data = ProductLanguageSerializer(product, context={
            'lang': lang,
            'request': request,
            'show_discount_price': True
        }).data
        
        # Get seller information
        seller = product.seller
        profile = getattr(seller, 'profile', None)
        
        seller_data = {
            'id': seller.id,
            'username': seller.username,
            'email': seller.email,
            'first_name': seller.first_name,
            'last_name': seller.last_name,
            'phone_number': seller.phone_number,
            'points': seller.points,
            'is_verified_seller': seller.is_verified_seller,
            'profile': {
                'bio': profile.bio if profile else None,
                'image': request.build_absolute_uri(profile.image.url) if profile and profile.image else None,
                'is_certified': profile.is_certified if profile else False,
            } if profile else None
        }
        
        # Add brand info if exists
        brand_data = None
        if product.brand:
            brand_data = {
                'id': product.brand.id,
                'name': product.brand.name,
                'logo': request.build_absolute_uri(product.brand.logo.url) if product.brand.logo else None,
            }
        
        response_data = {
            'product': product_data,
            'seller': seller_data,
            'brand': brand_data
        }
        
        return Response(response_data)

class CategoryProductsView(APIView):
    permission_classes = []
    
    def get(self, request, category_id):
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        category = get_object_or_404(Category, pk=category_id)
        
        # If it's a parent category, get products from all its children
        if category.is_parent:
            products = Product.objects.filter(
                category__in=category.children.all(),
                is_approved=True
            ).order_by('-created_at')
        else:
            # If it's a child category, get its products directly
            products = Product.objects.filter(
                category=category,
                is_approved=True
            ).order_by('-created_at')
     
        products = exclude_blocked_brands(products, request)

        # Paginate the results
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        
        serializer = ProductLanguageSerializer(page, many=True, context={
            'lang': lang,
            'request': request
        })
        
        return paginator.get_paginated_response(serializer.data)

class CategoryTopProductsView(APIView):
    permission_classes = []
    
    def get(self, request, category_id):
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        category = get_object_or_404(Category, pk=category_id)
        
        # If it's a parent category, get products from all its children
        if category.is_parent:
            products = Product.objects.filter(
                category__in=category.children.all(),
                is_approved=True
            ).order_by('-created_at')[:5]  # Limit to 5 products
        else:
            # If it's a child category, get its products directly
            products = Product.objects.filter(
                category=category,
                is_approved=True
            ).order_by('-created_at')[:5]  # Limit to 5 products
     
        products = exclude_blocked_brands(products, request)

        serializer = ProductLanguageSerializer(products, many=True, context={
            'lang': lang,
            'request': request
        })
        return Response({
            'count': products.count(),
            'results': serializer.data
        })

class ProductSearchView(APIView):
    permission_classes = []  # Accessible to anyone
    
    def get(self, request):
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        query = request.query_params.get('q', '').strip()
        if not query:
            return Response({"error": "Search query is required"}, status=400)
        
        # Get all filter parameters
        min_price = request.query_params.get('min_price')
        max_price = request.query_params.get('max_price')
        min_rating = request.query_params.get('min_rating')
        max_rating = request.query_params.get('max_rating')
        category_id = request.query_params.get('category_id')
        parent_category_id = request.query_params.get('parent_category_id')
        min_quantity = request.query_params.get('min_quantity')
        max_quantity = request.query_params.get('max_quantity')
        in_stock = request.query_params.get('in_stock')
        has_discount = request.query_params.get('has_discount')
        brand_id = request.query_params.get('brand_id')
        brand_slug = request.query_params.get('brand_slug')
        brand_name = request.query_params.get('brand_name')
        
        # Get sorting parameters
        sort_by = request.query_params.get('sort_by', '-created_at')  # Default: newest first
        sort_direction = request.query_params.get('sort_direction', 'desc')  # Default: descending
        
        # Validate sort options
        valid_sort_fields = ['price', 'created_at', 'rating']
        if sort_by not in valid_sort_fields:
            sort_by = 'created_at'
        
        # Validate sort direction
        sort_direction = sort_direction.lower()
        if sort_direction not in ['asc', 'desc']:
            sort_direction = 'desc'
        
        # Build sort parameter
        sort_prefix = '' if sort_direction == 'asc' else '-'
        sort_param = f"{sort_prefix}{sort_by}"
        
        # Base queryset with search
        products = Product.objects.filter(
            (Q(name_ar__icontains=query) | 
             Q(description_ar__icontains=query) |
             Q(name_en__icontains=query) | 
             Q(description_en__icontains=query) |
             Q(brand__name__icontains=query)) & 
            Q(is_approved=True)
            )
        
        # Apply category filters
        if category_id:
            products = products.filter(category_id=category_id)
        elif parent_category_id:
            products = products.filter(category__parent_id=parent_category_id)
        
        # Apply price filters
        if min_price:
            try:
                products = products.filter(price__gte=float(min_price))
            except (ValueError, TypeError):
                pass
                
        if max_price:
            try:
                products = products.filter(price__lte=float(max_price))
            except (ValueError, TypeError):
                pass
        
        # Apply rating filters
        if min_rating:
            try:
                products = products.filter(rating__gte=float(min_rating))
            except (ValueError, TypeError):
                pass
                
        if max_rating:
            try:
                products = products.filter(rating__lte=float(max_rating))
            except (ValueError, TypeError):
                pass

        # Apply quantity filters
        if min_quantity:
            try:
                products = products.filter(quantity__gte=int(min_quantity))
            except (ValueError, TypeError):
                pass
                
        if max_quantity:
            try:
                products = products.filter(quantity__lte=int(max_quantity))
            except (ValueError, TypeError):
                pass
                
        # Apply in-stock filter
        if in_stock and in_stock.lower() in ['true', '1', 'yes']:
            products = products.filter(quantity__gt=0)

        # Apply discount filter
        if has_discount and has_discount.lower() in ['true', '1', 'yes']:
            now = timezone.now()
            products = products.filter(
                Q(has_standalone_discount=True) &
                Q(standalone_discount_percentage__isnull=False) &
                (
                    Q(standalone_discount_start__isnull=True) | 
                    Q(standalone_discount_start__lte=now)
                ) &
                (
                    Q(standalone_discount_end__isnull=True) | 
                    Q(standalone_discount_end__gte=now)
                )
            )
        
        # Apply brand filters
        if brand_id:
            try:
                products = products.filter(brand_id=int(brand_id))
            except (TypeError, ValueError):
                pass

        if brand_slug:
            products = products.filter(brand__slug__iexact=brand_slug)

        if brand_name:
            products = products.filter(brand__name__icontains=brand_name)
        
        # Apply sorting
        products = products.order_by(sort_param)
        products = exclude_blocked_brands(products, request)

        # Pagination
        paginator = StandardResultsSetPagination()
        result_page = paginator.paginate_queryset(products, request)
        
        serializer = ProductLanguageSerializer(result_page, many=True, context={
            'lang': lang,
            'request': request,
            'show_discount_price': True
        })
        
        return paginator.get_paginated_response(serializer.data)

class UpdateProductQuantityView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def patch(self, request, product_id):
        product = get_object_or_404(Product, id=product_id, seller=request.user)
        
        quantity = request.data.get('quantity')
        if quantity is None:
            return Response(
                {"error": "Quantity field is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            quantity = int(quantity)
            if quantity < 0:
                return Response(
                    {"error": "Quantity must be a positive number"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "Quantity must be a valid integer"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        product.quantity = product.quantity + quantity
        product.save()
        
        return Response({
            "message": "Product quantity updated successfully",
            "product_id": product.id,
            "new_quantity": product.quantity
        })

class CartView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        from django.db import transaction
        from notifications.models import Notification

        cart, _ = Cart.objects.get_or_create(user=request.user)

        # Safety pass: clamp/remove any lines that exceed current stock
        with transaction.atomic():
            for item in cart.items.select_for_update().select_related('product'):
                p = item.product
                if p.quantity <= 0:
                    item.delete()
                    Notification.objects.create(
                        user=request.user,
                        notification_type='system_alert',
                        message_ar=f"تمت إزالة ({p.name_ar}) من السلة لنفاد المخزون.",
                        message_en=f"{p.name_en} was removed from your cart (out of stock).",
                        content_object=p
                    )
                elif item.quantity > p.quantity:
                    item.quantity = p.quantity
                    item.save(update_fields=['quantity'])
                    Notification.objects.create(
                        user=request.user,
                        notification_type='system_alert',
                        message_ar=f"تم تقليل كمية ({p.name_ar}) إلى {p.quantity} بسبب انخفاض المخزون.",
                        message_en=f"Quantity of {p.name_en} reduced to {p.quantity} due to low stock.",
                        content_object=p
                    )

        serializer = CartSerializer(cart)
        return Response(serializer.data)

class AddToCartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        product_id = request.data.get('product_id')
        quantity = request.data.get('quantity', 1)

        try:
            product = Product.objects.get(id=product_id, is_approved=True)
        except Product.DoesNotExist:
            return Response(
                {"error": "Product not found or not approved"},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            quantity = int(quantity)
            if quantity <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return Response(
                {"error": "Quantity must be a positive integer"},
                status=status.HTTP_400_BAD_REQUEST
            )

        cart, _ = Cart.objects.get_or_create(user=request.user)

        try:
            with transaction.atomic():
                # Check available quantity
                if quantity > product.quantity:
                    return Response(
                        {"error": f"Only {product.quantity} available in stock"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                cart_item, created = CartItem.objects.get_or_create(
                    cart=cart,
                    product=product,
                    defaults={'quantity': quantity}
                )

                if not created:
                    new_quantity = cart_item.quantity + quantity
                    if new_quantity > product.quantity:
                        return Response(
                            {"error": f"Cannot add {quantity} more (only {product.quantity - cart_item.quantity} available)"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    cart_item.quantity = new_quantity
                    cart_item.save()

                serializer = CartSerializer(cart)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

class UpdateCartItemView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, item_id):
        quantity = request.data.get('quantity')

        try:
            quantity = int(quantity)
            if quantity <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return Response(
                {"error": "Quantity must be a positive integer"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            cart_item = CartItem.objects.get(
                id=item_id,
                cart__user=request.user
            )
        except CartItem.DoesNotExist:
            return Response(
                {"error": "Item not found in your cart"},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            with transaction.atomic():
                if quantity > cart_item.product.quantity:
                    return Response(
                        {"error": f"Only {cart_item.product.quantity} available in stock"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                cart_item.quantity = quantity
                cart_item.save()
                
                serializer = CartSerializer(cart_item.cart)
                return Response(serializer.data)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

class RemoveFromCartView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, item_id):
        try:
            cart_item = CartItem.objects.get(
                id=item_id,
                cart__user=request.user
            )
            cart_item.delete()
            return Response(
                {"message": "Item removed from cart"},
                status=status.HTTP_204_NO_CONTENT
            )
        except CartItem.DoesNotExist:
            return Response(
                {"error": "Item not found in your cart"},
                status=status.HTTP_404_NOT_FOUND
            )

class WishlistView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
        serializer = WishlistSerializer(wishlist)
        return Response(serializer.data)

class AddToWishlistView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        product_id = request.data.get('product_id')
        
        try:
            product = Product.objects.get(id=product_id, is_approved=True)
        except Product.DoesNotExist:
            return Response(
                {"error": "Product not found or not approved"},
                status=status.HTTP_404_NOT_FOUND
            )

        wishlist, _ = Wishlist.objects.get_or_create(user=request.user)

        if WishlistItem.objects.filter(wishlist=wishlist, product=product).exists():
            return Response(
                {"error": "Product already in wishlist"},
                status=status.HTTP_400_BAD_REQUEST
            )

        WishlistItem.objects.create(wishlist=wishlist, product=product)
        
        serializer = WishlistSerializer(wishlist)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class RemoveFromWishlistView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, item_id):
        try:
            item = WishlistItem.objects.get(
                id=item_id,
                wishlist__user=request.user
            )
            item.delete()
            return Response(
                {"message": "Item removed from wishlist"},
                status=status.HTTP_204_NO_CONTENT
            )
        except WishlistItem.DoesNotExist:
            return Response(
                {"error": "Item not found in your wishlist"},
                status=status.HTTP_404_NOT_FOUND
            )

class MoveToCartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, item_id):
        try:
            wishlist_item = WishlistItem.objects.get(
                id=item_id,
                wishlist__user=request.user
            )
            
            cart, _ = Cart.objects.get_or_create(user=request.user)
            
            # Check if product already in cart
            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=wishlist_item.product,
                defaults={'quantity': 1}
            )
            
            if not created:
                if cart_item.quantity < cart_item.product.quantity:
                    cart_item.quantity += 1
                    cart_item.save()
            
            wishlist_item.delete()
            
            return Response(
                {
                    "message": "Item moved to cart",
                    "cart": CartSerializer(cart).data,
                    "wishlist": WishlistSerializer(wishlist_item.wishlist).data
                },
                status=status.HTTP_200_OK
            )
            
        except WishlistItem.DoesNotExist:
            return Response(
                {"error": "Item not found in your wishlist"},
                status=status.HTTP_404_NOT_FOUND
            )

class ActiveSaleEventListView(APIView):
    permission_classes = []

    def get(self, request):
        now = timezone.now()
        events = SaleEvent.objects.filter(
            start_date__lte=now,
            end_date__gte=now
        )
        
        # Handle language
        lang = request.headers.get('Accept-Language', 'en').lower()
        if lang not in ['ar', 'en']:
            lang = 'en'
        
        data = []
        for event in events:
            event_data = SaleEventSerializer(event, context={'request': request}).data
            data.append({
                'id': event.id,
                'name': event.name_ar if lang == 'ar' else event.name_en,
                'description': event.description_ar if lang == 'ar' else event.description_en,
                'start_date': event.start_date,
                'end_date': event.end_date,
                'image': event_data['image']
            })
        
        return Response(data)

class UpcomingSaleEventsView(APIView):
    permission_classes = [AllowAny]  # Accessible to everyone
    
    def get(self, request):
        """
        Get upcoming sale events (events that start in the future)
        """
        now = timezone.now()
        
        # Get upcoming sales (start date is in the future)
        upcoming_events = SaleEvent.objects.filter(
            Q(start_date__gt=now) |  # Future starts
            Q(start_date__lte=now, end_date__gt=now)  # Currently active but continuing
        ).order_by('start_date')
        
        # Handle language
        lang = request.headers.get('Accept-Language', 'ar').lower()
        if lang not in ['ar', 'en']:
            lang = 'ar'
        
        # Prepare response data
        data = []
        for event in upcoming_events:
            event_data = SaleEventSerializer(event, context={'request': request}).data
            
            # Calculate days until sale starts
            days_until_start = (event.start_date - now).days
            
            data.append({
                'id': event.id,
                'name': event.name_ar if lang == 'ar' else event.name_en,
                'description': event.description_ar if lang == 'ar' else event.description_en,
                'start_date': event.start_date,
                'end_date': event.end_date,
                'days_until_start': days_until_start,
                'image': event_data['image'],
                'status': 'upcoming',
                'total_products': event.products.count() if hasattr(event, 'products') else 0
            })
        
        return Response({
            'count': len(data),
            'upcoming_sales': data
        })

class ProductsInSaleView(APIView):
    permission_classes = []

    def get(self, request, sale_id):
        now = timezone.now()
        
        # Get the sale event to check if it exists and is active
        try:
            sale_event = SaleEvent.objects.get(
                id=sale_id,
                start_date__lte=now,
                end_date__gte=now
            )
        except SaleEvent.DoesNotExist:
            return Response(
                {"error": "Sale event not found or not active"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get products in sale with pagination
        products = ProductSale.objects.filter(
            sale_event_id=sale_id
        ).select_related('product', 'sale_event')
        
        # Apply pagination
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        
        if page is not None:
            serializer = ProductSaleSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        # Fallback if no pagination (shouldn't happen with StandardResultsSetPagination)
        serializer = ProductSaleSerializer(products, many=True)
        return Response(serializer.data)

class CreateSaleEventView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        # Create a mutable copy of the request data
        data = request.data.dict() if hasattr(request.data, 'dict') else request.data.copy()
        
        # Create serializer with data and context
        serializer = SaleEventSerializer(
            data=data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            # Save the sale event with the creator user
            sale_event = serializer.save(created_by=request.user)
            
            # Handle image separately if it exists
            if 'image' in request.FILES:
                sale_event.image = request.FILES['image']
                sale_event.save()
            
            # Return the created sale event data
            return Response(
                SaleEventSerializer(sale_event, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SaleEventDetailView(APIView):
    permission_classes = [AllowAny]  # Or set appropriate permissions
    
    def get(self, request, pk):
        try:
            sale_event = SaleEvent.objects.get(pk=pk)
            serializer = SaleEventSerializer(sale_event, context={'request': request})
            return Response(serializer.data)
        except SaleEvent.DoesNotExist:
            return Response(
                {"error": "Sale event not found"},
                status=status.HTTP_404_NOT_FOUND
            )

# Seller endpoints
class SellerProductSaleListView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def get(self, request):
        sales = ProductSale.objects.filter(
            product__seller=request.user
        ).select_related('sale_event', 'product')
        serializer = ProductSaleSerializer(sales, many=True)
        return Response(serializer.data)

class CreateProductSaleView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def post(self, request):
        serializer = CreateProductSaleSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UpdateProductSaleView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def patch(self, request):
        """
        Update discount percentage for a product in a specific sale
        Requires: product_id, sale_id, discount_percentage in request data
        """
        product_id = request.data.get('product_id')
        sale_id = request.data.get('sale_id')
        discount_percentage = request.data.get('discount_percentage')

        # Validate required fields
        if not all([product_id, sale_id, discount_percentage]):
            return Response(
                {"error": "product_id, sale_id, and discount_percentage are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Convert to proper types
            product_id = int(product_id)
            sale_id = int(sale_id)
            discount_percentage = float(discount_percentage)
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid data types. product_id and sale_id must be integers, discount_percentage must be a number"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate discount percentage range
        if not (0 <= discount_percentage <= 100):
            return Response(
                {"error": "Discount percentage must be between 0 and 100"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get the product sale instance
        try:
            product_sale = ProductSale.objects.get(
                product_id=product_id,
                sale_event_id=sale_id,
                product__seller=request.user  # Ensure the product belongs to the seller
            )
        except ProductSale.DoesNotExist:
            return Response(
                {"error": "Product sale not found or you don't have permission to edit it"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Update only the discount percentage
        serializer = UpdateProductSaleSerializer(
            product_sale,
            data={'discount_percentage': discount_percentage},
            partial=True,
            context={'request': request}
        )

        if serializer.is_valid():
            serializer.save()
            
            # Convert Decimal values to float for JSON serialization
            
            # Return updated data with product and sale info
            response_data = {
                'product_sale_id': product_sale.id,
            }
            
            return Response(response_data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class DeleteProductSaleView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def delete(self, request):
        """
        Remove a product from a sale
        Requires: product_id and sale_id in request data
        """
        product_id = request.data.get('product_id')
        sale_id = request.data.get('sale_id')

        # Validate required fields
        if not all([product_id, sale_id]):
            return Response(
                {"error": "product_id and sale_id are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Convert to proper types
            product_id = int(product_id)
            sale_id = int(sale_id)
        except (ValueError, TypeError):
            return Response(
                {"error": "product_id and sale_id must be integers"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get the product sale instance and verify ownership
        try:
            product_sale = ProductSale.objects.get(
                product_id=product_id,
                sale_event_id=sale_id,
                product__seller=request.user  # Ensure the product belongs to the seller
            )
        except ProductSale.DoesNotExist:
            return Response(
                {"error": "Product sale not found or you don't have permission to delete it"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Store information for response before deletion
        product_name_ar = product_sale.product.name_ar
        product_name_en = product_sale.product.name_en
        sale_name_ar = product_sale.sale_event.name_ar
        sale_name_en = product_sale.sale_event.name_en

        # Delete the product sale entry
        product_sale.delete()

        return Response(
            {
                "message": "Product successfully removed from sale",
                "details": {
                    "product_id": product_id,
                    "product_name_ar": product_name_ar,
                    "product_name_en": product_name_en,
                    "sale_id": sale_id,
                    "sale_name_ar": sale_name_ar,
                    "sale_name_en": sale_name_en
                }
            },
            status=status.HTTP_200_OK
        )

class ProductDiscountView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]
    
    def patch(self, request, pk):
        if not request.data:
            return Response(
                {"error": "No data provided for update"},
                status=status.HTTP_400_BAD_REQUEST
            )

        product = get_object_or_404(Product, pk=pk, seller=request.user)
        
        serializer = ProductDiscountSerializer(
            product,
            data=request.data,
            partial=True
        )
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            product = serializer.save()
            return Response(
                ProductSerializer(product).data,
                status=status.HTTP_200_OK
            )
        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .models import SellerBlock, User



from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .models import SellerBlock, User

class BlockSellerView(APIView):
    permission_classes = [IsAuthenticated, IsBuyerOrSeller]
    
    def post(self, request, seller_id):
        """
        حظر بائع معين
        """
        with transaction.atomic():
            if request.user.id == seller_id:
                return Response(
                    {"error": "لا يمكنك حظر نفسك"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            seller_to_block = get_object_or_404(User, id=seller_id)
            
            if not hasattr(seller_to_block, 'role'):
                return Response(
                    {"error": "المستخدم ليس لديه دور محدد"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if seller_to_block.role != 'seller':
                return Response(
                    {"error": "يمكن فقط حظر المستخدمين من نوع بائع"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if SellerBlock.objects.filter(
                blocker=request.user,
                blocked_seller=seller_to_block
            ).exists():
                return Response(
                    {"error": "لقد قمت بحظر هذا البائع مسبقًا"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            block = SellerBlock.objects.create(
                blocker=request.user,
                blocked_seller=seller_to_block
            )
            
            response_data = {
                "message": "تم حظر البائع بنجاح",
                "data": {
                    "id": block.id,
                    "blocker_id": block.blocker.id,
                    "blocker_username": block.blocker.username,
                    "blocked_seller_id": block.blocked_seller.id,
                    "blocked_seller_username": block.blocked_seller.username,
                    "created_at": block.created_at.strftime("%Y-%m-%d %H:%M:%S")
                }
            }
            
            return Response(response_data, status=status.HTTP_201_CREATED)

    def delete(self, request, seller_id):
        """
        إلغاء حظر بائع
        """
        with transaction.atomic():
            block = get_object_or_404(
                SellerBlock,
                blocker=request.user,
                blocked_seller_id=seller_id
            )
            block.delete()
            return Response(
                {"message": "تم إلغاء حظر البائع بنجاح"},
                status=status.HTTP_204_NO_CONTENT
            )

class BlockedSellersListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked_relations = SellerBlock.objects.filter(
            blocker=request.user
        ).select_related('blocked_seller', 'blocked_seller__profile')
        
        blocked_data = []
        for block in blocked_relations:
            seller = block.blocked_seller
            profile = getattr(seller, 'profile', None)

            blocked_data.append({
                "id": seller.id,
                "first_name": seller.first_name,
                "last_name": seller.last_name,
                "address": seller.address if hasattr(seller, 'address') else None,
                "phone_number": seller.phone_number if hasattr(seller, 'phone_number') else None,
                "image": request.build_absolute_uri(profile.image.url) if profile and profile.image else None,
                "bio": profile.bio if profile else None,
                "blocked_at": block.created_at.strftime("%Y-%m-%d %H:%M:%S")
            })

        return Response({"blocked_sellers": blocked_data}, status=status.HTTP_200_OK)

class UnapprovedProductsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]

    def get(self, request):
        lang = request.query_params.get('lang', 'ar')

        products = Product.objects.filter(is_approved=False).order_by('-created_at').select_related('category').prefetch_related('images')

        data = []
        for product in products:
            category = product.category
            category_name = category.name_en if lang == 'en' else category.name_ar

            # جلب روابط الصور كاملة
            images = [
                request.build_absolute_uri(image.image.url)
                for image in product.images.all()
            ]

            data.append({
                'id': product.id,
                'name': product.name_en if lang == 'en' else product.name_ar,
                'description': product.description_en if lang == 'en' else product.description_ar,
                'price': str(product.price),
                'category_id': category.id,
                'category_name': category_name,
                'images': images,
                'created_at': product.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })

        return Response({'unapproved_products': data}, status=status.HTTP_200_OK)

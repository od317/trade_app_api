
# products/models.py
from django.db import models
from accounts.models import EmailVerification, Purpose, User, Role
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, F  # Add these imports at the top
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify

class BrandStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'

class Brand(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    logo = models.ImageField(upload_to='brands/')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_brands'
    )
    description = models.TextField(blank=True, null=True)
    logo = models.ImageField(upload_to='brands/', blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=BrandStatus.choices,
        default=BrandStatus.PENDING
    )
    # 🔽 add these:
    rejection_reason = models.TextField(blank=True, null=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_brands'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # 🔽 add this

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
class BrandBlock(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocked_brands')
    brand = models.ForeignKey('Brand', on_delete=models.CASCADE, related_name='blocked_by_users')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'brand')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} blocked {self.brand.name}"

class status(models.TextChoices):
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'

class Category(models.Model):
    name_ar = models.CharField(max_length=100, verbose_name='الاسم بالعربية')
    name_en = models.CharField(max_length=100, verbose_name='الاسم بالإنجليزية')
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='children'
    )
    logo = models.ImageField(upload_to='categories/', blank=True, null=True)  # Added this line
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name_en or self.name_ar
    
    @property
    def is_parent(self):
        return self.parent is None
    
    @property
    def is_child(self):
        return self.parent is not None

class Product(models.Model):
    seller = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.ForeignKey(
        Category, 
        on_delete=models.CASCADE,
        related_name='products',
        limit_choices_to={'parent__isnull': False}  # This checks for child categories
    )
    rating = models.DecimalField(
        max_digits=3, 
        decimal_places=2,
        null=True,
        blank=True,
        default=None
    )
    name_ar = models.CharField(max_length=255, blank=True)
    name_en = models.CharField(max_length=255, blank=True)
    description_ar = models.TextField(blank=True)
    description_en = models.TextField(blank=True)
    brand = models.ForeignKey(
                'Brand',
                on_delete=models.SET_NULL,
                null=True,
                blank=True,
                related_name='products'
            )
    price = models.DecimalField(max_digits=10, decimal_places=2)
        
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name='Quantity in stock',
        help_text='Available quantity of this product'
    )

    status = models.CharField(max_length=20, choices=status.choices, default=status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    is_approved = models.BooleanField(default=False)
    
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_products'
    )

    approved_at = models.DateTimeField(null=True, blank=True)

    disapproval_reason_ar = models.TextField(blank=True, null=True)
    disapproval_reason_en = models.TextField(blank=True, null=True)
    has_standalone_discount = models.BooleanField(default=False)
   
    standalone_discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    standalone_discount_start = models.DateTimeField(null=True, blank=True)
    standalone_discount_end = models.DateTimeField(null=True, blank=True)
    CONDITION_CHOICES = [
    ('new', 'New'),
    ('like_new', 'Like New'),
    ('used', 'Used'),
    ('damaged', 'Damaged'),
    ('unsaleable', 'Unsaleable')
    ]
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='new')
    @property
    def current_price(self):
        """Returns either discounted price or regular price"""
        now = timezone.now()
        if (self.has_standalone_discount and 
            self.standalone_discount_percentage and
            (not self.standalone_discount_start or self.standalone_discount_start <= now) and
            (not self.standalone_discount_end or now <= self.standalone_discount_end)):
            return self.price * (100 - self.standalone_discount_percentage) / 100
        return self.price
  
    def has_active_standalone_discount(self):
        """
        Check if product currently has an active standalone discount
        """
        if not self.has_standalone_discount or not self.standalone_discount_percentage:
            return False
            
        now = timezone.now()
        start_ok = (self.standalone_discount_start is None) or (self.standalone_discount_start <= now)
        end_ok = (self.standalone_discount_end is None) or (now <= self.standalone_discount_end)
        
        return start_ok and end_ok
    
    @property
    def has_active_discount(self):
        """Check if product has any active discount (standalone or sale)"""
        now = timezone.now()
        
        # Check standalone discount
        if self.has_standalone_discount and self.standalone_discount_percentage:
            start_ok = (self.standalone_discount_start is None) or (self.standalone_discount_start <= now)
            end_ok = (self.standalone_discount_end is None) or (now <= self.standalone_discount_end)
            if start_ok and end_ok:
                return True
        
        # Check sale discounts
        active_sales = self.sales.filter(
            sale_event__start_date__lte=now,
            sale_event__end_date__gte=now
        ).exists()
        
        return active_sales

    @property
    def active_discount_percentage(self):
        """Get the current active discount percentage"""
        if not self.has_active_discount:
            return None
            
        now = timezone.now()
        
        # Check standalone discount first
        if self.has_standalone_discount and self.standalone_discount_percentage:
            start_ok = (self.standalone_discount_start is None) or (self.standalone_discount_start <= now)
            end_ok = (self.standalone_discount_end is None) or (now <= self.standalone_discount_end)
            if start_ok and end_ok:
                return self.standalone_discount_percentage
        
        # Check sale discounts
        active_sale = self.sales.filter(
            sale_event__start_date__lte=now,
            sale_event__end_date__gte=now
        ).first()
        
        return active_sale.discount_percentage if active_sale else None

    def get_dirty_fields(self):
        """Track which fields have changed"""
        if not self.pk:
            return {}
        
        current_state = type(self).objects.get(pk=self.pk)
        dirty_fields = {}
        
        for field in self._meta.fields:
            current_value = getattr(current_state, field.name)
            new_value = getattr(self, field.name)
            if current_value != new_value:
                dirty_fields[field.name] = new_value
        
        return dirty_fields

    def save(self, *args, **kwargs):
            # Track approval changes
            if self.pk:  # Only for existing products
                old = Product.objects.get(pk=self.pk)
                if not old.is_approved and self.is_approved:
                    # Approval happened
                    super().save(*args, **kwargs)
                    return
            super().save(*args, **kwargs)
    
class ProductEditRequest(models.Model):
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
    ]
    
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='edit_requests')
    seller = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Fields that can be edited
    name_ar = models.CharField(max_length=255, blank=True, null=True)
    name_en = models.CharField(max_length=255, blank=True, null=True)
    description_ar = models.TextField(blank=True, null=True)
    description_en = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    rejection_reason = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Edit request for {self.product.name_en} by {self.seller.username}"

class EditRequestImage(models.Model):
    edit_request = models.ForeignKey(ProductEditRequest, on_delete=models.CASCADE, related_name='new_images')
    image = models.ImageField(upload_to='products/edit_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Image for edit request #{self.edit_request.id}"
    
class SellerBlock(models.Model):


    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocked_sellers')  # المستخدم الذي قام بالحظر
    blocked_seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocked_by_users')  # البائع المحظور
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked_seller')  # لا يمكن حظر نفس البائع مرتين

class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='products/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

class SaleEvent(models.Model):
    name_ar = models.CharField(max_length=100, default='')
    name_en = models.CharField(max_length=100, default='')
    description_ar = models.TextField(default='')
    description_en = models.TextField(default='')
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    image = models.ImageField(upload_to='sales/', null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_sales'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.name_en

    def save(self, *args, **kwargs):
        # Auto-set is_active based on dates
        now = timezone.now()
        self.is_active = (self.start_date <= now <= self.end_date)
        super().save(*args, **kwargs)
        
class ProductSale(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='sales'
    )
    sale_event = models.ForeignKey(
        SaleEvent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='product_sales'
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']
        constraints = [
            models.CheckConstraint(
                check=Q(end_date__gt=F('start_date')),
                name='end_date_after_start_date'
            ),
            models.UniqueConstraint(
                fields=['product', 'sale_event'],
                name='unique_product_sale_event',
                condition=Q(sale_event__isnull=False)
            )
        ]

    def save(self, *args, **kwargs):
        # Validate dates and set is_active
        now = timezone.now()
        if now < self.start_date:
            self.is_active = False
        elif now > self.end_date:
            self.is_active = False
        else:
            self.is_active = True
        
        # Ensure either sale_event or standalone discount
        if not self.sale_event and not (self.start_date and self.end_date):
            raise ValidationError("Standalone discounts must have start/end dates")
            
        super().save(*args, **kwargs)

    @property
    def discounted_price(self):
        return self.product.price * (100 - self.discount_percentage) / 100

    @property
    def status(self):
        now = timezone.now()
        if now < self.start_date:
            return "Scheduled"
        elif now > self.end_date:
            return "Expired"
        return "Active"

# class Notification(models.Model):
#     user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
#     title = models.CharField(max_length=255)
#     body = models.TextField()
#     url = models.URLField(blank=True, null=True)  # يمكن أن تشير إلى تفاصيل منتج أو صفحة أخرى

#     is_read = models.BooleanField(default=False)
#     created_at = models.DateTimeField(auto_now_add=True)

#     def __str__(self):
#         return self.title

class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='favorited_by')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')  # لا يمكن تكرار نفس المنتج في المفضلة
        ordering = ['-added_at']  # الأحدث أولًا

    def __str__(self):
        return f"{self.user.username} - {self.product}"

class Cart(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='cart'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_items(self):
        return self.items.aggregate(total= Sum('quantity'))['total'] or 0

    @property
    def total_price(self):
        return self.items.aggregate(
            total= Sum(F('quantity') * F('product__price'))
        )['total'] or 0

class CartItem(models.Model):
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='cart_items'
    )
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('cart', 'product')  # Prevent duplicate items

    def clean(self):
        if self.quantity > self.product.quantity:
            raise ValidationError(
                f"Only {self.product.quantity} available in stock"
            )

    def save(self, *args, **kwargs):
        self.full_clean()  # Validate before saving
        super().save(*args, **kwargs)

class Wishlist(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='wishlist'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Wishlist of {self.user.username}"

class WishlistItem(models.Model):
    wishlist = models.ForeignKey(
        Wishlist,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='wishlisted_by'
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('wishlist', 'product')  # Prevent duplicates
        ordering = ['-added_at']  # Newest items first

    def __str__(self):
        return f"{self.product.name_en} in wishlist"
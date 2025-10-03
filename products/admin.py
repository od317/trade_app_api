from django.contrib import admin
from .models import SaleEvent, ProductSale

@admin.register(SaleEvent)
class SaleEventAdmin(admin.ModelAdmin):
    list_display = ('name_ar', 'name_en', 'start_date', 'end_date', 'is_active', 'created_by')
    list_filter = ('is_active', 'start_date', 'end_date')
    search_fields = ('name_ar', 'name_en', 'description_ar', 'description_en')
    readonly_fields = ('is_active', 'created_by', 'created_at')
    
    fieldsets = (
        (None, {
            'fields': ('name_ar', 'name_en', 'description_ar', 'description_en')
        }),
        ('Dates', {
            'fields': ('start_date', 'end_date')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'is_active')
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:  # Only set creator on first save
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(ProductSale)
class ProductSaleAdmin(admin.ModelAdmin):
    list_display = ('product', 'sale_event', 'discount_percentage', 'is_active')
    list_filter = ('sale_event', 'is_active')
    raw_id_fields = ('product',)
    readonly_fields = ('is_active',)
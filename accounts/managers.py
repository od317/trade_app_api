from django.contrib.auth.base_user import BaseUserManager
from django.utils.translation import gettext_lazy as _


class CustomUserManager(BaseUserManager):
    """
    مدير مستخدم مخصص لإنشاء المستخدمين العاديين والمشرفين (Super Admin)
    هذا المدير يستخدم مع نموذج المستخدم المخصص CustomUser
    """

    def create_user(self, email, password=None, **extra_fields):
        """إنشاء مستخدم عادي"""
        if not email:
            raise ValueError(_('البريد الإلكتروني مطلوب'))

        email = self.normalize_email(email)
        extra_fields.setdefault('is_active', True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """إنشاء مشرف (سوبر أدمن)"""
        if not email:
            raise ValueError(_('البريد الإلكتروني مطلوب'))

        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', 'superadmin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('المشرف يجب أن يكون is_staff=True'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('المشرف يجب أن يكون is_superuser=True'))

        return self.create_user(email, password, **extra_fields)

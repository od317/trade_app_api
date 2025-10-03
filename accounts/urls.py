
from django.urls import path
from .views import (
    ListUsersView, ListSellersView, ListDeliveryView, ListAdminsView,PublicUserProfileView
,ConfirmEmailChangeAPIView,RequestEmailChangeAPIView, VerifyAdminDeliveryCodeAPIView,
 UserProfileView,RequestPasswordResetCodeView,CreateAdminUserView,CreateDeliveryUserView,
 ResetPasswordView,VerifyResetCodeView,SuperAdminLoginAPIView,LoginAPIView,EmailVerificationAPIView,
 VerifyCodeAPIView,ResendVerificationCodeAPIView,CompleteRegistrationAPIView,UpdateMyLocationView,
 UpdateProfileImageView,UserProfileAPIView

)

urlpatterns = [
        path('user/profile/', UserProfileAPIView.as_view(), name='user-profile'),
    ## ادخال الايميل و الدور  لارسال رمز التحقق
    path('EmailVerificationAPI/', EmailVerificationAPIView.as_view(), name='EmailVerificationAPIView'),
    ## التحقق من الايميل  نرسل الايميل  فقط و نبعث التوكن بالهيدر    
    path('VerifyCodeAPI/', VerifyCodeAPIView.as_view(), name='VerifyCodeAPIView'),
    ##  طلب اعادة ارسال رمز التحقق فقط نبعث التوكن بالهيدر
    path('ResendVerificationCodeAPI/', ResendVerificationCodeAPIView.as_view(), name='ResendVerificationCodeAPIView'),
    ## اكمال ادخال المعلومات   و نبعث التوكن بالهيدر 
    path('CompleteRegistrationAPI/', CompleteRegistrationAPIView.as_view(), name='CompleteRegistrationAPIView'),
    ## تسجيل الدخول ندخل الايميل و كلمة السر
    path('LoginAPI/', LoginAPIView.as_view(), name='LoginAPIView'),
    ## طلب اعادة تعيين كلمة السر يدخل الايميل و يتم ارسال رمز تحقق
    path('RequestPasswordResetCode/', RequestPasswordResetCodeView.as_view(), name='RequestPasswordResetCodeView'),
    ## ادخال رمز التحقق لاعادة تعيين كلمة سر
    path('VerifyResetCode/', VerifyResetCodeView.as_view(), name='VerifyResetCodeView'),
    path('ResetPassword/', ResetPasswordView.as_view(), name='ResetPasswordView'),# إعادة تعيين كلمة المرور
    ## انشاء دديليفري  يدخل فقط الايميل و يتم ارسال رمز تتحقق
    path('CreateDeliveryUser/', CreateDeliveryUserView.as_view(), name='CreateDeliveryUserView'),
    ## انشاء ادمن  يدخل فقط الايميل و يتم ارسال رمز تتحقق
    path('CreateAdminUser/', CreateAdminUserView.as_view(), name='CreateAdminUserView'),
    ## التحقق من رمز التحقق  للديليفري و الادمن حيث يدخل الايميل وو رمز التحقق 
    path('VerifyAdminDeliveryCodeAPI/', VerifyAdminDeliveryCodeAPIView.as_view(), name='VerifyAdminDeliveryCodeAPI'),
    ## عرض الملف الشخصي
    path('MyProfile/', UserProfileView.as_view(), name='profile-me'),
    path('profile/image/', UpdateProfileImageView.as_view(), name='update-profile-image'),
    path('RequestEmailChangeAPI/', RequestEmailChangeAPIView.as_view(), name='RequestEmailChangeAPI'),# طلب تغيير الايميل و ادخال ايميل جديد
    path('ConfirmEmailChangeAPI/', ConfirmEmailChangeAPIView.as_view(), name='ConfirmEmailChangeAPI'),# تغيير الايميل و التحقق من الرمز
    ## رؤية قائمة 
    path('users/', ListUsersView.as_view(), name='list-users'),
    path('sellers/', ListSellersView.as_view(), name='list-sellers'),
    path('delivery/', ListDeliveryView.as_view(), name='list-delivery'),
    path('admins/', ListAdminsView.as_view(), name='list-admins'),
    ## عرض  بروفايل اي مستخدم
    path('profile/<int:user_id>/', PublicUserProfileView.as_view(), name='public-profile'),
    path('profile/location/', UpdateMyLocationView.as_view(), name='profile-update-location'),

]




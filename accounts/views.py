# accounts/views.py
from django.db import IntegrityError, transaction
from django.utils import timezone
from datetime import timedelta
from django.core.validators import validate_email as django_validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password, ValidationError as PasswordValidationError
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import F
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ObjectDoesNotExist
from accounts.models import Profile
from .serializers import LocationUpdateSerializer,ProfileSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser
import random
import jwt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .serializers import UserProfileDisplaySerializer
from cryptography.fernet import Fernet

from .models import EmailVerification, Purpose, User, Role
from .utils import (
    decode_jwt_token,
    decrypt_token,
    generate_verification_code,
    encrypt_token,
    send_verification_email,
    create_jwt_token,
    create_monthly_token
)

ALLOWED_ROLES = ['user', 'seller']

class EmailVerificationAPIView(APIView):
    def post(self, request):
        email = request.data.get('email')
        role = request.data.get('role')

        if not email or not role:
            return Response({'error': 'يرجى إدخال البريد الإلكتروني والدور.'}, status=400)

        if role not in ALLOWED_ROLES:
            return Response({'error': 'الدور غير مسموح. المسموح فقط: user أو seller.'}, status=400)

        try:
            django_validate_email(email)
        except DjangoValidationError:
            return Response({'error': 'صيغة البريد الإلكتروني غير صحيحة.'}, status=400)

        now = timezone.now()
        purpose = Purpose.EMAIL_VERIFICATION

        try:
            with transaction.atomic():
                record = EmailVerification.objects.select_for_update().get(email=email, purpose=purpose)
                
                if  User.objects.filter(email=email).exists() or record.has_user:
                    return Response({
                        'error': 'هذا البريد الإلكتروني مسجل بالفعل ولديه مستخدم.',
                        'verified': True,
                        'has_user': True
                    }, status=400)
                
                # الحالة 2: إذا كان محققًا وليس له مستخدم
                elif record.is_verified and not record.has_user:
                    # تحقق إذا مضى أكثر من ساعة على التحقق
                    if record.verified_at and (now - record.verified_at) > timedelta(hours=1):
                        # يستمر في عملية الإرسال بعد تحديث الحالة
                        record.is_verified = False
                        record.verified_at = None
                        record.save(update_fields=['is_verified', 'verified_at'])
                    else:
                        # لم يمضِ ساعة على التحقق
                        remaining_time = int((timedelta(hours=1) - (now - record.verified_at)).total_seconds() / 60)
                        return Response({
                            'error': 'هذا البريد الإلكتروني تم التحقق منه مؤخراً.',
                            'verified': True,
                            'has_user': False
                        }, status=400)
                
                # الحالة 3: إذا لم يكن محققًا أو تم إعادة تعيينه
                
                # تحقق من عدد الإرسال اليومي
                if record.first_sent_today and record.first_sent_today.date() == now.date():
                    if record.send_count_today >= 5:
                        return Response({'error': 'تم تجاوز الحد الأقصى لإرسال رمز التحقق اليوم (5 مرات).'}, status=429)
                else:
                    # إذا كان أول إرسال اليوم، نعيد تعيين العداد
                    record.send_count_today = 0
                    record.first_sent_today = now

                # تحقق من المدة منذ آخر إرسال
                if record.last_sent_at and (now - record.last_sent_at) < timedelta(minutes=1):
                    return Response({'error': 'يرجى الانتظار دقيقة واحدة قبل إعادة الإرسال.'}, status=429)

                # إنشاء رمز وتوكن جديدين
                # code = generate_verification_code()
                code = "123"
                encrypted = encrypt_token(code)
                token = create_jwt_token({'email': email, 'role': role}, expires_minutes=60)

                # تحديث سجل التحقق
                record.encrypted_code = encrypted
                record.send_count_today += 1
                record.last_sent_at = now
                record.expires_at = now + timedelta(minutes=60)
                record.role = role
                record.current_token = token
                record.is_verified = False  # تأكيد إعادة التعيين
                record.verified_at = None
                
                record.save(update_fields=[
                    'encrypted_code', 'send_count_today', 'last_sent_at', 
                    'expires_at', 'role', 'current_token', 'is_verified',
                    'verified_at', 'first_sent_today'
                ])

                send_verification_email(email, code)
                return Response({'message': 'تم إرسال رمز التحقق بنجاح.', 'token': token}, status=200)

        except EmailVerification.DoesNotExist:
            # أول مرة يتم الإرسال
            # code = generate_verification_code()
            code = "123"
            encrypted = encrypt_token(code)
            token = create_jwt_token({'email': email, 'role': role}, expires_minutes=60)

            EmailVerification.objects.create(
                email=email,
                role=role,
                purpose=purpose,
                encrypted_code=encrypted,
                send_count_today=1,
                first_sent_today=now,
                last_sent_at=now,
                expires_at=now + timedelta(minutes=60),
                is_verified=False,
                has_user=False,
                current_token=token
            )

            send_verification_email(email, code)
            return Response({'message': 'تم إرسال رمز التحقق بنجاح .', 'token': token}, status=201)
        
class SuperAdminLoginAPIView(APIView):

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response({'error': 'البريد الإلكتروني وكلمة المرور مطلوبان'}, status=400)

        try:
            django_validate_email(email)
        except DjangoValidationError:
            return Response({'error': 'صيغة البريد الإلكتروني غير صالحة'}, status=400)

        try:
            user = User.objects.get(email=email)

            if user.role != 'superadmin':
                return Response({'error': 'صلاحيات الدخول غير مسموحة'}, status=403)

            if not user.check_password(password):
                return Response({'error': 'بيانات الاعتماد غير صحيحة'}, status=400)

            if not user.is_active:
                return Response({'error': 'الحساب غير مفعل'}, status=403)

            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])

            payload = {
                'user_id': user.id,
                'email': user.email,
                'role': user.role,
            }
            token = create_monthly_token(payload)
            user.current_token_user = token
            user.save(update_fields=['current_token_user'])

            return Response({
                'message': 'تم تسجيل الدخول بنجاح',
                'token': token,
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'role': user.role,
                    'last_login': user.last_login,
                }
            }, status=200)

        except User.DoesNotExist:
            return Response({'error': 'بيانات الاعتماد غير صحيحة'}, status=404)


VALID_ROLES = ['user', 'seller']  # 

class VerifyCodeAPIView(APIView):
    authentication_classes = []  # إلغاء المصادقة الافتراضية
    permission_classes = []

    def post(self, request):
        try:
            # 1. استخراج التوكن من الهيدر المخصص
            token = self._extract_token_from_header(request)
            payload = decode_jwt_token(token)

            email = payload.get('email')
            role = payload.get('role')

            if not email or not role:
                raise ValidationError("التوكن لا يحتوي على البريد الإلكتروني أو الدور.")

            # 2. الحصول على رمز التحقق من المستخدم
            input_code = request.data.get('code')
            if not input_code:
                raise ValidationError("يرجى إدخال رمز التحقق.")

            # 3. جلب سجل التحقق المرتبط بالبريد
            try:
                record = EmailVerification.objects.get(
                    email=email,
                    purpose=Purpose.EMAIL_VERIFICATION
                )
            except EmailVerification.DoesNotExist:
                return Response(
                    {'error': 'لا يوجد طلب تحقق مرتبط بهذا البريد الإلكتروني.'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 4. التحقق من مطابقة التوكن
            if record.current_token != token:
                return Response({'error': 'التوكن غير صالح أو غير مطابق.'}, status=status.HTTP_401_UNAUTHORIZED)

            # 5. تحقق إن كان قد تم التحقق مسبقًا
            if record.is_verified:
                return Response({
                    'message': 'تم التحقق من البريد مسبقًا.',
                    'verified': True,
                    'email': email,
                    'role': role
                }, status=status.HTTP_200_OK)

            # 6. تحقق من انتهاء صلاحية الرمز
            if timezone.now() > record.expires_at:
                return Response(
                    {'error': 'انتهت صلاحية رمز التحقق. الرجاء إعادة الإرسال.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 7. تحقق من تطابق الرمز بعد فك تشفيره
            try:
                decrypted_code = decrypt_token(record.encrypted_code)
            except Exception:
                return Response({'error': 'فشل فك تشفير رمز التحقق.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            if input_code != decrypted_code:
                return Response({'error': 'رمز التحقق غير صحيح.'}, status=status.HTTP_400_BAD_REQUEST)

            # 8. تحديث حالة التحقق
            
            record.is_verified = True
            record.verified_at = timezone.now()
            record.save(update_fields=['is_verified', 'verified_at'])

            return Response({
                'message': 'تم التحقق بنجاح.',
                'verified': True,
                'email': email,
                'role': role
            }, status=status.HTTP_200_OK)

        except ValidationError as ve:
            return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({'error': f'حدث خطأ: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _extract_token_from_header(self, request):
        """استخراج التوكن من هيدر X-Email-Token"""
        token = request.headers.get('X-Email-Token', '').strip()
        if not token:
            raise ValidationError('يرجى إرسال التوكن في الهيدر X-Email-Token.')
        return token
    
class ResendVerificationCodeAPIView(APIView):
    authentication_classes = []  # لأننا لا نستخدم توكن الدخول هنا
    permission_classes = []

    def post(self, request):
        # 1. جلب التوكن من الهيدر المخصص
        email_token = request.headers.get('X-Email-Token')
        if not email_token:
            return Response({'error': 'يرجى إرسال التوكن في الهيدر X-Email-Token'}, status=401)

        # 2. فك التوكن
        try:
            payload = decode_jwt_token(email_token)
        except Exception:
            return Response({'error': 'التوكن غير صالح أو منتهي'}, status=401)

        # 3. استخراج البيانات
        email = payload.get('email')
        role = payload.get('role')
        if not email or not role:
            return Response({'error': 'التوكن لا يحتوي على البريد أو الدور'}, status=400)

        now = timezone.now()
        purpose = Purpose.EMAIL_VERIFICATION

        try:
            record = EmailVerification.objects.get(email=email, purpose=purpose)

            # 4. تحقق من تطابق التوكن الحالي
            if record.current_token != email_token:
                return Response({'error': 'التوكن لا يطابق سجل التحقق الحالي.'}, status=401)

            # 5. تحقق من حالة التحقق
            if record.is_verified:
                return Response({'message': 'تم التحقق مسبقًا. يرجى تسجيل الدخول.'}, status=200)

            # 6. الحد اليومي للإرسال
            if record.first_sent_today and record.first_sent_today.date() == now.date():
                if record.send_count_today >= 5:
                    return Response({'error': 'تم تجاوز الحد اليومي لإرسال الرمز (5 مرات).'}, status=429)
            else:
                record.send_count_today = 0
                record.first_sent_today = now

            # 7. تحقق من الفاصل الزمني
            if record.last_sent_at and (now - record.last_sent_at) < timedelta(minutes=1):
                return Response({'error': 'يرجى الانتظار دقيقة قبل إعادة الإرسال.'}, status=429)

            # 8. توليد رمز جديد
            # new_code = generate_verification_code()
            new_code = "123"
            encrypted_code = encrypt_token(new_code)
            new_token = create_jwt_token({'email': email, 'role': role}, expires_minutes=60)

            # 9. تحديث السجل
            record.encrypted_code = encrypted_code
            record.send_count_today = F('send_count_today') + 1
            record.last_sent_at = now
            record.expires_at = now + timedelta(minutes=60)
            record.current_token = new_token
            record.save(update_fields=[
                'encrypted_code', 'send_count_today', 'last_sent_at',
                'expires_at', 'first_sent_today', 'current_token'
            ])

            send_verification_email(email, new_code)
            return Response({'message': 'تم إرسال رمز تحقق جديد.', 'token': new_token}, status=200)

        except EmailVerification.DoesNotExist:
            return Response({'error': 'البريد الإلكتروني غير مسجل.'}, status=404)


class CompleteRegistrationAPIView(APIView):
    authentication_classes = []  # تعطيل نظام المصادقة العام
    permission_classes = []

    REQUIRED_FIELDS = [
        'username', 'first_name', 'last_name',
        'phone_number', 'address', 'password', 'confirm_password'
    ]

    def post(self, request):
        # 1. الحصول على التوكن من هيدر مخصص
        email_token = request.headers.get('X-Email-Token')
        if not email_token:
            return Response({'error': 'يرجى إرسال التوكن في الهيدر X-Email-Token'}, status=status.HTTP_401_UNAUTHORIZED)

        # 2. فك التوكن
        try:
            payload = decode_jwt_token(email_token)
        except Exception:
            return Response({'error': 'التوكن غير صالح أو منتهي الصلاحية.'}, status=status.HTTP_401_UNAUTHORIZED)

        email = payload.get('email')
        role = payload.get('role')
        if not email:
            return Response({'error': 'التوكن لا يحتوي على بريد إلكتروني.'}, status=status.HTTP_400_BAD_REQUEST)

        # 3. الحصول على سجل التحقق
        try:
            record = EmailVerification.objects.get(
                email=email,
                purpose=Purpose.EMAIL_VERIFICATION,
                is_verified=True,
                has_user=False
            )
        except EmailVerification.DoesNotExist:
            return Response({'error': 'لا يوجد بريد محقق لم يُستخدم بعد لإنشاء حساب.'}, status=status.HTTP_400_BAD_REQUEST)

        # 4. التحقق من انتهاء صلاحية التحقق
        if record.verified_at and timezone.now() - record.verified_at > timedelta(hours=1):
            return Response({'error': 'مرّت أكثر من ساعة على التحقق، الرجاء إعادة التحقق.'}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data

        # 5. تحقق من الحقول المطلوبة
        missing = [f for f in self.REQUIRED_FIELDS if not data.get(f)]
        if missing:
            return Response({'error': f'الحقول التالية مطلوبة: {", ".join(missing)}'}, status=status.HTTP_400_BAD_REQUEST)

        # 6. تحقق من صحة صيغة البريد
        try:
            django_validate_email(email)
        except DjangoValidationError:
            return Response({'error': 'صيغة البريد الإلكتروني غير صحيحة.'}, status=status.HTTP_400_BAD_REQUEST)

        # 7. تحقق من تطابق كلمتي المرور
        if data['password'] != data['confirm_password']:
            return Response({'error': 'كلمة المرور وتأكيدها غير متطابقين.'}, status=status.HTTP_400_BAD_REQUEST)

        # 8. تحقق من قوة كلمة المرور
        try:
            validate_password(data['password'])
        except PasswordValidationError as ve:
            return Response({'error': 'كلمة المرور ضعيفة.', 'details': ve.messages}, status=status.HTTP_400_BAD_REQUEST)

        # 9. تحقق من عدم تكرار المستخدم
        if User.objects.filter(email=email).exists():
            return Response({'error': 'البريد الإلكتروني مستخدم مسبقًا.'}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(username=data['username']).exists():
            return Response({'error': 'اسم المستخدم مستخدم مسبقًا.'}, status=status.HTTP_400_BAD_REQUEST)

        # 10. إنشاء المستخدم
        try:
            user = User.objects.create_user(
                email=email,
                username=data['username'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                phone_number=data['phone_number'],
                address=data['address'],
                role=role,
                password=data['password']
            )
        except IntegrityError:
            return Response({'error': 'حدث خطأ أثناء إنشاء المستخدم. حاول باسم مستخدم مختلف.'}, status=status.HTTP_400_BAD_REQUEST)

        # 11. تحديث سجل التحقق
        record.has_user = True
        record.save(update_fields=['has_user'])

        return Response({
            'message': 'تم إنشاء الحساب بنجاح. يمكنك الآن تسجيل الدخول.',
            'email': user.email,
            'username': user.username
        }, status=status.HTTP_201_CREATED)


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.validators import validate_email as django_validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from datetime import timedelta

from .models import User
from .utils import create_monthly_token  # يفترض أنه ينشئ JWT بصلاحية 30 يوماً

class LoginAPIView(APIView):

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        # 1. تحقق من إرسال الحقلين
        if not email or not password:
            return Response(
                {'error': 'حقل البريد الإلكتروني وكلمة المرور كلاهما مطلوب.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. تحقق من صيغة الإيميل
        try:
            django_validate_email(email)
        except DjangoValidationError:
            return Response(
                {'error': 'صيغة البريد الإلكتروني غير صالحة.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. حاول جلب المستخدم
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {'error': 'بيانات الاعتماد غير صحيحة.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # 4. تحقق من صلاحية الحساب
        if not user.is_active:
            return Response(
                {'error': 'الحساب معطل، يرجى التواصل مع الدعم.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # 5. تحقق من كلمة المرور
        if not user.check_password(password):
            return Response(
                {'error': 'بيانات الاعتماد غير صحيحة.'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        payload = {
            'user_id': user.id,
            'email': user.email,
            'role': user.role,
        }
        token = create_monthly_token(payload)

        # 6. تحديث آخر دخول
        user.current_token_user=token
        user.last_login = timezone.now()
        user.save(update_fields=['last_login','current_token_user'])

        

        return Response({
            'message': 'تم تسجيل الدخول بنجاح.',
            'token': token,
            'user': {
                'id': user.id,
                'email': user.email,
                'role': user.role,
                'last_login': user.last_login,
            }
        }, status=status.HTTP_200_OK)

class VerifyResetCodeView(APIView):
    authentication_classes = []  # إلغاء المصادقة الافتراضية
    permission_classes = []

    def post(self, request):
        # 1. الحصول على التوكن من هيدر مخصص
        token = request.headers.get('X-Email-Token')
        if not token:
            return Response({'detail': 'يجب إرسال التوكن في الهيدر X-Email-Token.'}, status=status.HTTP_401_UNAUTHORIZED)

        # 2. فك التوكن
        try:
            payload = decode_jwt_token(token)
        except Exception:
            return Response({'detail': 'التوكن غير صالح أو منتهي.'}, status=status.HTTP_401_UNAUTHORIZED)

        email = payload.get('email')
        if not email:
            return Response({'detail': 'التوكن لا يحتوي على بريد إلكتروني.'}, status=status.HTTP_400_BAD_REQUEST)

        # 3. الحصول على الرمز من المستخدم
        input_code = request.data.get('code')
        if not input_code:
            return Response({'detail': 'الرجاء إدخال رمز التحقق.'}, status=status.HTTP_400_BAD_REQUEST)

        # 4. البحث عن سجل التحقق الخاص بإعادة تعيين كلمة المرور
        try:
            verification = EmailVerification.objects.get(
                email=email,
                purpose=Purpose.PASSWORD_RESET
            )
        except ObjectDoesNotExist:
            return Response({'detail': 'لا يوجد طلب تحقق نشط لهذا البريد.'}, status=status.HTTP_404_NOT_FOUND)

        # 5. التحقق من مطابقة التوكن
        if verification.current_token != token:
            return Response({'detail': 'التوكن غير مطابق للسجل الحالي.'}, status=status.HTTP_401_UNAUTHORIZED)

        # 6. التحقق من انتهاء صلاحية الرمز
        if timezone.now() > verification.expires_at:
            return Response({'detail': 'انتهت صلاحية رمز التحقق.'}, status=status.HTTP_400_BAD_REQUEST)

        # 7. فك تشفير الرمز ومقارنته
        try:
            decrypted_code = decrypt_token(verification.encrypted_code)
        except Exception:
            return Response({'detail': 'فشل التحقق من الرمز.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if input_code != decrypted_code:
            return Response({'detail': 'رمز التحقق غير صحيح.'}, status=status.HTTP_400_BAD_REQUEST)

        # 8. تحديث حالة التحقق
        verification.is_verified = True
        verification.verified_at = timezone.now()
        verification.save(update_fields=['is_verified', 'verified_at'])

        return Response({'detail': 'تم التحقق بنجاح، يمكنك الآن تعيين كلمة مرور جديدة.'}, status=status.HTTP_200_OK)


class RequestPasswordResetCodeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')

        if not email:
            return Response({'error': 'البريد الإلكتروني مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        purpose = Purpose.PASSWORD_RESET

        try:
            user = User.objects.get(email=email)
            role = user.role
        except User.DoesNotExist:
            return Response({'error': 'لا يوجد مستخدم مسجل بهذا البريد الإلكتروني.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            ev = EmailVerification.objects.get(email=email, purpose=purpose)

            if ev.first_sent_today and ev.first_sent_today.date() == now.date():
                if ev.send_count_today >= 3:
                    return Response({'error': 'لقد تجاوزت الحد الأقصى لعدد طلبات رمز التحقق اليوم (3 مرات).'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            else:
                ev.send_count_today = 0
                ev.first_sent_today = now

            if ev.last_sent_at and (now - ev.last_sent_at) < timedelta(minutes=1):
                wait_seconds = 60 - int((now - ev.last_sent_at).total_seconds())
                return Response({'error': f'يرجى الانتظار {wait_seconds} ثانية قبل طلب رمز جديد.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

            # code = generate_verification_code()
            code = "123"
            encrypted_code = encrypt_token(code)

            ev.encrypted_code = encrypted_code
            ev.send_count_today += 1
            ev.last_sent_at = now
            ev.is_verified = False
            ev.verified_at = None
            ev.has_user = True
            ev.expires_at = now + timedelta(minutes=30)

            token_payload = {'email': email, 'role': role, 'purpose': purpose}
            jwt_token = create_jwt_token(token_payload, expires_minutes=60)
            ev.current_token = jwt_token
            ev.save()

            send_verification_email(email, code)

            return Response({
                'message': 'تم إرسال رمز التحقق إلى بريدك الإلكتروني.',
                'token': jwt_token,
            }, status=status.HTTP_200_OK)

        except EmailVerification.DoesNotExist:
            # code = generate_verification_code()
            code = "123"
            encrypted_code = encrypt_token(code)

            expires_at = now + timedelta(minutes=30)
            token_payload = {'email': email, 'role': role, 'purpose': purpose}
            jwt_token = create_jwt_token(token_payload, expires_minutes=60)

            EmailVerification.objects.create(
                email=email,
                role=role,
                purpose=purpose,
                encrypted_code=encrypted_code,
                send_count_today=1,
                first_sent_today=now,
                last_sent_at=now,
                is_verified=False,
                verified_at=None,
                has_user=True,
                expires_at=expires_at,
                current_token=jwt_token
            )

            send_verification_email(email, code)

            return Response({
                'message': 'تم إرسال رمز التحقق إلى بريدك الإلكتروني.',
                'token': jwt_token,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': 'حدث خطأ داخلي. حاول مرة أخرى لاحقاً.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class ResetPasswordView(APIView):
    def post(self, request):
        try:
            # 1. استخراج التوكن من الهيدر المخصص
            token = self._extract_token_from_custom_header(request)

            # 2. فك التوكن
            payload = decode_jwt_token(token)
            email = payload.get('email')
            role = payload.get('role')

            if not email or not role:
                return Response({'detail': 'التوكن لا يحتوي على معلومات كافية.'}, status=status.HTTP_400_BAD_REQUEST)

            # 3. البحث عن سجل التحقق
            try:
                verification = EmailVerification.objects.get(email=email, purpose=Purpose.PASSWORD_RESET)
            except ObjectDoesNotExist:
                return Response({'detail': 'لا يوجد طلب تحقق نشط لهذا البريد.'}, status=status.HTTP_404_NOT_FOUND)

            # 4. التحقق من مطابقة التوكن
            if verification.current_token != token:
                return Response({'detail': 'التوكن غير متطابق مع السجل الحالي.'}, status=status.HTTP_401_UNAUTHORIZED)

            if not verification.is_verified:
                return Response({'detail': 'لم يتم التحقق من البريد الإلكتروني بعد.'}, status=status.HTTP_400_BAD_REQUEST)

            # 5. التحقق من صلاحية الرمز (اختياري لكن ينصح به)
            if verification.expires_at and timezone.now() > verification.expires_at:
                return Response({'detail': 'انتهت صلاحية رمز التحقق. يرجى إعادة الإرسال.'}, status=status.HTTP_400_BAD_REQUEST)

            # 6. التحقق من صحة كلمات المرور
            new_password = request.data.get('new_password')
            confirm_password = request.data.get('confirm_password')

            if not new_password or not confirm_password:
                return Response({'detail': 'يرجى إدخال كلمة المرور وتأكيدها.'}, status=status.HTTP_400_BAD_REQUEST)

            if new_password != confirm_password:
                return Response({'detail': 'كلمتا المرور غير متطابقتين.'}, status=status.HTTP_400_BAD_REQUEST)

            if len(new_password) < 8:
                return Response({'detail': 'كلمة المرور يجب أن تكون 8 أحرف على الأقل.'}, status=status.HTTP_400_BAD_REQUEST)

            # 7. تغيير كلمة المرور
            try:
                user = User.objects.get(email=email)
            except ObjectDoesNotExist:
                return Response({'detail': 'المستخدم غير موجود.'}, status=status.HTTP_404_NOT_FOUND)

            user.set_password(new_password)
            user.save()

            # 8. تحديث سجل التحقق
            verification.has_user = True
            verification.current_token = None
            verification.expires_at = timezone.now()
            verification.save(update_fields=['has_user', 'current_token', 'expires_at'])

            return Response({'detail': 'تم تعيين كلمة المرور بنجاح. يمكنك الآن تسجيل الدخول.'}, status=status.HTTP_200_OK)

        except ValidationError as ve:
            return Response({'detail': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': f'حدث خطأ غير متوقع: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _extract_token_from_custom_header(self, request):
        """
        استخراج التوكن من هيدر مخصص X-Email-Token
        """
        token = request.headers.get('X-Email-Token', '').strip()
        if not token:
            raise ValidationError('يرجى إرسال التوكن في الهيدر X-Email-Token.')
        return token


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from accounts.permissionsUsers import IsSuperAdmin,IsSeller,IsAdmin,IsSeller,IsSuperAdminOrAdmin

class CreateAdminUserView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request):
        email = request.data.get('email')

        if not email:
            return Response({'error': 'يرجى إدخال البريد الإلكتروني .'}, status=400)

        try:
            django_validate_email(email)
        except DjangoValidationError:
            return Response({'error': 'صيغة البريد الإلكتروني غير صحيحة.'}, status=400)

        now = timezone.now()
        purpose = Purpose.EMAIL_VERIFICATION

        try:
            with transaction.atomic():
                record = EmailVerification.objects.select_for_update().get(email=email, purpose=purpose)

                if User.objects.filter(email=email).exists() or record.has_user:
                    return Response({
                        'error': 'هذا البريد الإلكتروني مسجل بالفعل ولديه مستخدم.',
                        'verified': True,
                        'has_user': True
                    }, status=400)

                elif record.is_verified and not record.has_user:
                    if record.verified_at and (now - record.verified_at) > timedelta(hours=1):
                        record.is_verified = False
                        record.verified_at = None
                        record.save(update_fields=['is_verified', 'verified_at'])
                    else:
                        return Response({
                            'error': 'هذا البريد الإلكتروني تم التحقق منه مؤخراً.',
                            'verified': True,
                            'has_user': False
                        }, status=400)

                if record.first_sent_today and record.first_sent_today.date() == now.date():
                    if record.send_count_today >= 5:
                        return Response({'error': 'تم تجاوز الحد الأقصى لإرسال رمز التحقق اليوم (5 مرات).'}, status=429)
                else:
                    record.send_count_today = 0
                    record.first_sent_today = now

                if record.last_sent_at and (now - record.last_sent_at) < timedelta(minutes=1):
                    return Response({'error': 'يرجى الانتظار دقيقة واحدة قبل إعادة الإرسال.'}, status=429)

                # توليد رمز التحقق فقط دون توكن
                # code = generate_verification_code()
                code = "123"
                encrypted = encrypt_token(code)

                record.encrypted_code = encrypted
                record.send_count_today += 1
                record.last_sent_at = now
                record.expires_at = now + timedelta(minutes=60)
                record.role = 'admin'
                record.current_token = None  # ⛔️ لا توكن هنا
                record.is_verified = False
                record.verified_at = None

                record.save(update_fields=[
                    'encrypted_code', 'send_count_today', 'last_sent_at',
                    'expires_at', 'role', 'current_token', 'is_verified',
                    'verified_at', 'first_sent_today'
                ])

                send_verification_email(email, code)
                return Response({'message': 'تم إرسال رمز التحقق بنجاح إلى بريد الموظف الإداري.'}, status=200)

        except EmailVerification.DoesNotExist:
            # code = generate_verification_code()
            code = "123"
            encrypted = encrypt_token(code)

            EmailVerification.objects.create(
                email=email,
                role='admin',
                purpose=purpose,
                encrypted_code=encrypted,
                send_count_today=1,
                first_sent_today=now,
                last_sent_at=now,
                expires_at=now + timedelta(minutes=60),
                is_verified=False,
                has_user=False,
                current_token=None  # ⛔️ لا توكن هنا
            )

            send_verification_email(email, code)
            return Response({'message': 'تم إرسال رمز التحقق بنجاح لأول مرة.'}, status=201)

class CreateDeliveryUserView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]

    def post(self, request):
        email = request.data.get('email')

        if not email:
            return Response({'error': 'يرجى إدخال البريد الإلكتروني.'}, status=400)

        try:
            django_validate_email(email)
        except DjangoValidationError:
            return Response({'error': 'صيغة البريد الإلكتروني غير صحيحة.'}, status=400)

        now = timezone.now()
        purpose = Purpose.EMAIL_VERIFICATION

        try:
            with transaction.atomic():
                record = EmailVerification.objects.select_for_update().get(email=email, purpose=purpose)

                if User.objects.filter(email=email).exists() or record.has_user:
                    return Response({
                        'error': 'هذا البريد الإلكتروني مسجل بالفعل ولديه مستخدم.',
                        'verified': True,
                        'has_user': True
                    }, status=400)

                elif record.is_verified and not record.has_user:
                    if record.verified_at and (now - record.verified_at) > timedelta(hours=1):
                        record.is_verified = False
                        record.verified_at = None
                        record.save(update_fields=['is_verified', 'verified_at'])
                    else:
                        return Response({
                            'error': 'هذا البريد الإلكتروني تم التحقق منه مؤخراً.',
                            'verified': True,
                            'has_user': False
                        }, status=400)

                if record.first_sent_today and record.first_sent_today.date() == now.date():
                    if record.send_count_today >= 5:
                        return Response({'error': 'تم تجاوز الحد الأقصى لإرسال رمز التحقق اليوم (5 مرات).'}, status=429)
                else:
                    record.send_count_today = 0
                    record.first_sent_today = now

                if record.last_sent_at and (now - record.last_sent_at) < timedelta(minutes=1):
                    return Response({'error': 'يرجى الانتظار دقيقة واحدة قبل إعادة الإرسال.'}, status=429)

                # code = generate_verification_code()
                code = "123"
                encrypted = encrypt_token(code)

                record.encrypted_code = encrypted
                record.send_count_today += 1
                record.last_sent_at = now
                record.expires_at = now + timedelta(minutes=60)
                record.role = 'delivery'
                record.current_token = None  # ⛔️ لا يتم توليد توكن
                record.is_verified = False
                record.verified_at = None

                record.save(update_fields=[
                    'encrypted_code', 'send_count_today', 'last_sent_at',
                    'expires_at', 'role', 'current_token', 'is_verified',
                    'verified_at', 'first_sent_today'
                ])

                send_verification_email(email, code)
                return Response({'message': 'تم إرسال رمز التحقق بنجاح إلى بريد موظف التوصيل.'}, status=200)

        except EmailVerification.DoesNotExist:
            # code = generate_verification_code()
            code = "123"
            encrypted = encrypt_token(code)

            EmailVerification.objects.create(
                email=email,
                role='delivery',
                purpose=purpose,
                encrypted_code=encrypted,
                send_count_today=1,
                first_sent_today=now,
                last_sent_at=now,
                expires_at=now + timedelta(minutes=60),
                is_verified=False,
                has_user=False,
                current_token=None  # ⛔️ لا يتم توليد توكن
            )

            send_verification_email(email, code)
            return Response({'message': 'تم إرسال رمز التحقق لأول مرة بنجاح.'}, status=201)

class VerifyAdminDeliveryCodeAPIView(APIView):
    """
    التحقق من رمز التحقق لحسابات دليفري أو أدمن فقط، مع إرجاع التوكن
    حتى وإن لم يتم التحقق إذا كان الدور يسمح بذلك.
    """

    def post(self, request):
        email = request.data.get('email')
        code = request.data.get('code')

        if not email or not code:
            return Response({'error': 'يرجى إدخال البريد الإلكتروني ورمز التحقق.'}, status=400)

        try:
            record = EmailVerification.objects.get(email=email, purpose=Purpose.EMAIL_VERIFICATION)
        except EmailVerification.DoesNotExist:
            return Response({'error': 'لا يوجد طلب تحقق مرتبط بهذا البريد.'}, status=404)

        # فقط يسمح لـ admin أو delivery
        if record.role not in ['admin', 'delivery']:
            return Response({'error': 'هذا البريد ليس مخصصًا لحساب أدمن أو دليفري.'}, status=403)

        now = timezone.now()

        # إذا تحقق مسبقاً
        if record.is_verified:
            token = create_jwt_token({'email': record.email, 'role': record.role}, expires_minutes=120)
            record.current_token = token
            record.expires_at = now + timedelta(minutes=120)
            record.save(update_fields=['current_token', 'expires_at'])

            return Response({
                'message': 'تم التحقق مسبقًا.',
                'verified': True,
                'email': record.email,
                'role': record.role
            }, status=200)

        # إذا لم يتم التحقق بعد
        try:
            decrypted_code = decrypt_token(record.encrypted_code)
        except Exception:
            decrypted_code = None

        if decrypted_code == code and now <= record.expires_at:
            # ✅ الرمز صحيح وغير منتهي
            record.is_verified = True
            record.verified_at = now
            token = create_jwt_token({'email': record.email, 'role': record.role}, expires_minutes=120)
            record.current_token = token
            record.expires_at = now + timedelta(minutes=120)
            record.save(update_fields=['is_verified', 'verified_at', 'current_token', 'expires_at'])

            return Response({
                'message': 'تم التحقق بنجاح.',
                'verified': True,
                'token': token,
                'email': record.email,
                'role': record.role
            }, status=200)
        else:
            # ❌ الرمز خاطئ أو منتهي، لكن نعطي التوكن لأن الدور admin/delivery
            token = create_jwt_token({'email': record.email, 'role': record.role}, expires_minutes=120)
            record.current_token = token
            record.expires_at = now + timedelta(minutes=120)
            record.save(update_fields=['current_token', 'expires_at'])

            return Response({
                'error': 'رمز التحقق غير صحيح أو منتهي، لم يتم التحقق بعد.',
                'verified': False,
                'token': token,
                'email': record.email,
                'role': record.role
            }, status=400)

############################ APTS PROFILE################################################################################## 
# profiles/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .serializers import UserProfileDisplaySerializer, UserProfileUpdateSerializer

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        serializer = UserProfileDisplaySerializer(user)
        return Response(serializer.data)

    def put(self, request):
        user = request.user
        serializer = UserProfileUpdateSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'message': 'تم تحديث البروفايل بنجاح.',
                'data': serializer.data
            })
        return Response(serializer.errors, status=400)

class RequestEmailChangeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        New_Email = request.data.get('New_Email')
        user = request.user
        current_email = user.email

        # 1. التحقق من وجود البريد الجديد
        if not New_Email:
            return Response({'error': 'يرجى إدخال البريد الإلكتروني الجديد.'}, status=400)

        # 2. التحقق من صيغة البريد
        try:
            django_validate_email(New_Email)
        except DjangoValidationError:
            return Response({'error': 'صيغة البريد الإلكتروني غير صحيحة.'}, status=400)

        # 3. التحقق من أن البريد غير مستخدم
        if New_Email == current_email:
            return Response({'error': 'البريد الجديد هو نفسه البريد الحالي.'}, status=400)

        if EmailVerification.objects.filter(new_email=New_Email, is_verified=False).exists() or \
           EmailVerification.objects.filter(email=New_Email, is_verified=True).exists() or \
           user.__class__.objects.filter(email=New_Email).exists():
            return Response({'error': 'هذا البريد الإلكتروني مستخدم بالفعل.'}, status=400)

        # 4. تجهيز البيانات
        now = timezone.now()
        # code = generate_verification_code()
        code = "123"
        encrypted = encrypt_token(code)
        purpose = Purpose.EMAIL_CHANGE

        # 5. حفظ سجل التحقق أو تحديثه
        EmailVerification.objects.update_or_create(
            email=current_email,
            purpose=purpose,
            defaults={
                'encrypted_code': encrypted,
                'send_count_today': 1,
                'first_sent_today': now,
                'last_sent_at': now,
                'expires_at': now + timedelta(minutes=60),
                'is_verified': False,
                'has_user': True,
                'role': user.role,
                'current_token': None,
                'new_email': New_Email,  # تخزين البريد الجديد
            }
        )

        # 6. إرسال رمز التحقق
        send_verification_email(New_Email, code)

        return Response({'message': 'تم إرسال رمز التحقق إلى البريد الجديد.'}, status=200)
    
class ConfirmEmailChangeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        input_code = request.data.get("code")

        if not input_code:
            return Response({'error': 'يرجى إدخال رمز التحقق.'}, status=400)

        try:
            # نبحث في سجل التحقق باستخدام الإيميل الأصلي من المستخدم
            record = EmailVerification.objects.get(
                email=user.email,
                purpose=Purpose.EMAIL_CHANGE,
                is_verified=False,
                new_email__isnull=False
            )
        except EmailVerification.DoesNotExist:
            return Response({'error': 'لا يوجد طلب تغيير بريد نشط لهذا المستخدم.'}, status=404)

        # تحقق من صلاحية الرمز (ساعة واحدة)
        if timezone.now() > record.expires_at:
            return Response({'error': 'انتهت صلاحية رمز التحقق. الرجاء طلب رمز جديد.'}, status=400)

        try:
            decrypted_code = decrypt_token(record.encrypted_code)
        except Exception:
            return Response({'error': 'فشل فك تشفير الرمز.'}, status=500)

        if input_code != decrypted_code:
            return Response({'error': 'رمز التحقق غير صحيح.'}, status=400)

        # كل شيء صحيح، نقوم بتحديث البريد
        New_email = record.new_email

        # تحقق إضافي: لا يكون مستخدم آخر يملك البريد
        if User.objects.filter(email=New_email).exclude(id=user.id).exists():
            return Response({'error': 'البريد الجديد مستخدم من قبل حساب آخر.'}, status=400)

        # تحديث البريد في جدول المستخدم
        user.email = New_email
        user.save(update_fields=["email"])

        # تحديث سجل التحقق
        record.is_verified = True
        record.verified_at = timezone.now()
        record.new_email = None  # نفرغ الحقل بعد استخدامه
        record.save(update_fields=["is_verified", "verified_at", "new_email"])

        return Response({'message': 'تم تغيير البريد الإلكتروني بنجاح.'}, status=200)


from .serializers import PublicUserProfileSerializer

class ListUsersView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]

    def get(self, request):
        users = User.objects.filter(role='user')
        serializer = PublicUserProfileSerializer(users, many=True)
        return Response(serializer.data)


class ListSellersView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]

    def get(self, request):
        sellers = User.objects.filter(role='seller')
        serializer = PublicUserProfileSerializer(sellers, many=True)
        return Response(serializer.data)


class ListDeliveryView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrAdmin]

    def get(self, request):
        delivery_users = User.objects.filter(role='delivery')
        serializer = PublicUserProfileSerializer(delivery_users, many=True)
        return Response(serializer.data)


class ListAdminsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        admins = User.objects.filter(role='admin')
        serializer = PublicUserProfileSerializer(admins, many=True)
        return Response(serializer.data)
from django.shortcuts import get_object_or_404
    
class PublicUserProfileView(APIView):

    def get(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        serializer = PublicUserProfileSerializer(user)
        return Response(serializer.data)
    
class UpdateMyLocationView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        ser = LocationUpdateSerializer(profile, data=request.data, partial=True)
        if ser.is_valid():
            # enforce both lat/lng together
            data = ser.validated_data
            if ('latitude' in data) ^ ('longitude' in data):
                return Response(
                    {"error": "Send both latitude and longitude together."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            ser.save()
            return Response({"message": "Location updated successfully.", "profile": ser.data})
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    
class UpdateProfileImageView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)  # Important for file uploads

    def patch(self, request):
        """
        Update only the profile image
        """
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if image is provided
        if 'image' not in request.FILES and 'image' not in request.data:
            return Response({'error': 'No image provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Handle the image update
        serializer = ProfileSerializer(
            profile, 
            data={'image': request.FILES.get('image') or request.data.get('image')}, 
            partial=True
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response({
                'message': 'Profile image updated successfully',
                'image_url': profile.image.url if profile.image else None
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        """
        Delete the profile image
        """
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)
        
        if profile.image:
            # Delete the file from storage
            profile.image.delete(save=False)
            profile.image = None
            profile.save()
            return Response({'message': 'Profile image deleted successfully'}, status=status.HTTP_200_OK)
        
        return Response({'error': 'No profile image to delete'}, status=status.HTTP_400_BAD_REQUEST)
    

class UserProfileAPIView(APIView):
    """
    API endpoint for users to retrieve their own profile data
    Only the authenticated user can access their own information
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Retrieve the authenticated user's profile data
        """
        user = request.user
        
        # Serialize the user data
        serializer = UserProfileDisplaySerializer(user)
        
        return Response({
            'message': 'User profile retrieved successfully',
            'data': serializer.data
        }, status=status.HTTP_200_OK)
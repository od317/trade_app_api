# profiles/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Profile

User = get_user_model()

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['image', 'bio','latitude', 'longitude',
            'address_line', 'city', 'region', 'country', 'postal_code',]
    
    extra_kwargs = {
            'image': {'required': False}
        }

    def validate(self, attrs):
        lat = attrs.get('latitude')
        lng = attrs.get('longitude')
        if lat is not None and (lat < -90 or lat > 90):
            raise serializers.ValidationError("latitude must be between -90 and 90.")
        if lng is not None and (lng < -180 or lng > 180):
            raise serializers.ValidationError("longitude must be between -180 and 180.")
        return attrs

class UserProfileDisplaySerializer(serializers.ModelSerializer):
    profile = ProfileSerializer()
    email = serializers.EmailField(read_only=True)

    class Meta:
        model = User
        fields = [
            'username', 'first_name', 'last_name',
            'phone_number', 'address', 'email', 'profile',
        ]

class UserProfileUpdateSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(required=False)
    email = serializers.EmailField(read_only=True)

    class Meta:
        model = User
        fields = [
            'username', 'first_name', 'last_name',
            'phone_number', 'address', 'email', 'profile'
        ]

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        profile = instance.profile

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        for attr, value in profile_data.items():
            setattr(profile, attr, value)
        profile.save()
        return instance

class ProfileLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = [
            'latitude', 'longitude', 'address_line', 
            'city', 'region', 'country', 'postal_code',
            'is_certified'
        ]
        read_only_fields = fields

class PublicUserProfileSerializer(serializers.ModelSerializer):
    bio = serializers.CharField(source="profile.bio", allow_blank=True, read_only=True)
    image = serializers.ImageField(source="profile.image", read_only=True)
    points = serializers.IntegerField(read_only=True)
    is_verified_seller = serializers.BooleanField(read_only=True)
    location = ProfileLocationSerializer(source="profile", read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'role',
            'phone_number', 'address', 'bio', 'image',
            'points', 'is_verified_seller', 'location'
        ]

class LocationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = [
            'latitude', 'longitude',
            'address_line', 'city', 'region', 'country', 'postal_code'
        ]

    def validate(self, attrs):
        lat = attrs.get('latitude')
        lng = attrs.get('longitude')
        if lat is None or lng is None:
            raise serializers.ValidationError("latitude and longitude are required.")
        if not (-90 <= float(lat) <= 90):
            raise serializers.ValidationError("latitude must be between -90 and 90.")
        if not (-180 <= float(lng) <= 180):
            raise serializers.ValidationError("longitude must be between -180 and 180.")
        return attrs
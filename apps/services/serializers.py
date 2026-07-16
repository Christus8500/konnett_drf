from rest_framework import serializers

from apps.services.models import Category, Service

# Serializer for the Category model, used to serialize and deserialize category data.
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]
        read_only_fields = ["id", "slug"]


# Serializer for the Service model, used to serialize and deserialize service data.
class ServiceReadSerializer(serializers.ModelSerializer):
    class InlineCategorySerializer(serializers.ModelSerializer):
        class Meta:
            model = Category
            fields = ["id", "name"]
            read_only_fields = ["id"]

    provider_id = serializers.UUIDField(source="provider.id", read_only=True)
    provider_name = serializers.CharField(source="provider.fullname", read_only=True)
    provider_image = serializers.ImageField(source="provider.profile_image", read_only=True)
    
    category = InlineCategorySerializer(read_only=True)

    class Meta:
        model = Service
        fields = ["id", "provider_id", "provider_name", "provider_image", "category", "title", "description", "minimum_price", "is_active"]


# Serializer for creating and updating Service instances, 
# allowing the provider to specify the category, title, description, minimum price, and active status of the service.
class ServiceWriteSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())

    class Meta:
        model = Service
        fields = ["category", "title", "description", "minimum_price", "is_active"]


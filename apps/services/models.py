from django.db import models
from django.core.validators import MinValueValidator
from django.utils.text import slugify

from apps.core.models import UUIDModel

# Create your models here.


# Category model representing a category of services, with a unique name and slug.
class Category(UUIDModel):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    requires_secondary_location = models.BooleanField(default=False)

    # Override the save method to automatically generate a unique slug based on the category name.
    def save(self, *args, **kwargs):
        base_slug = slugify(self.name) or "category"

        existing_slugs = set(
            Category.objects.filter(slug__startswith=base_slug)
            .exclude(pk=self.pk)
            .values_list("slug", flat=True)
        )

        slug = base_slug
        counter = 1

        while slug in existing_slugs:
            slug = f"{base_slug}-{counter}"
            counter += 1

        self.slug = slug

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# Service model representing a service offered by a provider, linked to a category.
class Service(UUIDModel):
    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="services"
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="services"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    minimum_points = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title

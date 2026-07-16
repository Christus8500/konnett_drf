from decimal import Decimal

from django.db import models
from django.core.validators import MinValueValidator
from django.utils.text import slugify

from apps.core.models import UUIDModel

# Create your models here.

# Category model representing a category of services, with a unique name and slug.
class Category(UUIDModel):
    name = models.CharField(
        max_length=100,
        unique=True
    )
    slug = models.SlugField(max_length=255, unique=True, blank=True)

    # Override the save method to automatically generate a unique slug based on the category name.
    def save(self, *args, **kwargs):
        base_slug = slugify(self.name) or "category"
        slug = base_slug
        counter = 1

        while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        self.slug = slug

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# Service model representing a service offered by a provider, linked to a category.
class Service(UUIDModel):
    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE,
        related_name="services"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="services"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    minimum_price = models.DecimalField(
        max_digits=20, decimal_places=2, validators=[MinValueValidator(Decimal("100.00"))])
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils.text import slugify

from apps.core.models import TimeStampedModel, UUIDModel

# Create your models here.


# Category model representing a category of services, with a unique name and slug.
class Category(UUIDModel, TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True, editable=False)
    requires_secondary_location = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="unique_lower_category_name"),
        ]

    # Override the save method to automatically generate a unique slug based on the category name.
    def save(self, *args, **kwargs):
        # Generate the slug once and keep it stable afterwards
        if not self.slug:
            self.slug = self._generate_unique_slug()
            if "update_fields" in kwargs and kwargs["update_fields"] is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "slug"}
        super().save(*args, **kwargs)

    def _generate_unique_slug(self):
        max_length = self._meta.get_field("slug").max_length
        base_slug = (slugify(self.name) or "category")[: max_length - 10]

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
        return slug

    def __str__(self):
        return self.name


# Service model representing a service offered by a provider, linked to a category.
class Service(UUIDModel, TimeStampedModel):
    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="services"
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="services"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    minimum_points = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(minimum_points__gte=1),
                name="service_minimum_points_gte_1",
            ),
            models.UniqueConstraint(
                fields=["provider", "category", "title"],
                name="unique_service_title_per_provider_category",
            ),
        ]

    def __str__(self):
        return self.title

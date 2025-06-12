from django.contrib import admin
from .models import Video

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ['caption', 'video', 'processed_video']
    readonly_fields = ['processed_video']
from django.contrib import admin
from django import forms
from .models import Video

class VideoAdminForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = '__all__'
        widgets = {
            'video': forms.FileInput(attrs={
                'accept': 'video/mp4,video/x-matroska,video/avi,video/quicktime,video/webm'
            })
        }

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    form = VideoAdminForm
    list_display = ['caption', 'video', 'processed_video']
    readonly_fields = ['processed_video']
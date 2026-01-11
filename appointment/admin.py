from django.contrib import admin
from .models import Doctor, Appointment, Profile


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        'patient_name',
        'doctor',
        'appointment_date',
        'appointment_time',
        'status',
    )
    list_filter = ('status', 'doctor')
    search_fields = ('patient_name', 'patient_email')


admin.site.register(Doctor)
admin.site.register(Profile)

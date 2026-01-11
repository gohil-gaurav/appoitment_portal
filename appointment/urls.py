from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [

    path('', views.home, name='home'),
    path('doctors/', views.doctors, name='doctors'),
    path('doctors/<int:doctor_id>/', views.doctor_detail, name='doctor_detail'),
    

    path('book/<int:doctor_id>/', views.book_appointment, name='book'),
    path('reschedule/<int:appointment_id>/', views.reschedule_appointment, name='reschedule_appointment'),


    path('patient/dashboard/', views.patient_dashboard, name='patient_dashboard'),
    path('patient/reviews/', views.my_reviews, name='my_reviews'),
    path('patient/reminders/', views.manage_reminders, name='manage_reminders'),
    

    path('doctor/dashboard/', views.doctor_dashboard, name='doctor_dashboard'),
    path('doctor/availability/', views.manage_availability, name='manage_availability'),
    path('doctor/calendar/', views.appointment_calendar, name='appointment_calendar'),


    path('login/', auth_views.LoginView.as_view(
        template_name='login.html'
    ), name='login'),

     path('activate/<uidb64>/<token>/', views.activate_account, name='activate_account'),

    path('logout/', auth_views.LogoutView.as_view(
        next_page='/login/'
    ), name='logout'),

    path('signup/patient/', views.signup_patient, name='signup_patient'),
    path('signup/doctor/', views.signup_doctor, name='signup_doctor'),


    path('api/appointments/<int:appointment_id>/update-status/', 
         views.update_appointment_status, 
         name='update_appointment_status'),
    
    path('api/appointments/<int:appointment_id>/details/', 
         views.get_appointment_details, 
         name='get_appointment_details'),
    
    path('api/appointments/available-slots/', 
         views.get_available_slots, 
         name='get_available_slots'),
    
    path('api/appointments/available-slots-v2/', 
         views.get_available_slots_v2, 
         name='get_available_slots_v2'),
    
    path('api/appointments/bulk-update/', 
         views.bulk_update_appointments, 
         name='bulk_update_appointments'),
    
    path('api/appointments/export/', 
         views.export_appointments, 
         name='export_appointments'),
    
    path('api/analytics/dashboard/', 
         views.analytics_dashboard, 
         name='analytics_dashboard'),
    
    path('api/notifications/<int:notification_id>/mark-read/', 
         views.mark_notification_read, 
         name='mark_notification_read'),
    
    path('api/notifications/mark-all-read/', 
         views.mark_all_notifications_read, 
         name='mark_all_notifications_read'),
    
    path('api/search/appointments/', 
         views.search_appointments, 
         name='search_appointments'),
    
    path('api/calendar/events/', 
         views.calendar_events, 
         name='calendar_events'),
    
    # Review endpoints
    path('api/doctors/<int:doctor_id>/add-review/', 
         views.add_review, 
         name='add_review'),
    
    path('reviews/<int:review_id>/edit/', 
         views.edit_review, 
         name='edit_review'),
]

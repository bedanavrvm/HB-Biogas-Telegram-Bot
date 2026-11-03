from django.urls import path
from . import views

urlpatterns = [
    path('',views.browser),
    path('template/',views.browser,{'action':'template'}),
    path('<uuid:upload_id>/',views.browser),
    path('<uuid:upload_id>/<str:action>/',views.browser),
]

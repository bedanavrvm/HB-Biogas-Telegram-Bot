"""Do not expose vendor credential/email editors as a recovery workflow."""
from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.mfa.models import Authenticator
from django.contrib import admin
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.urls import path
import uuid
from unfold.admin import ModelAdmin

from .models import StaffBrowserAdmission, StaffBrowserSetupGrant, StaffTOTPReplayState


# Django's admin autodiscovery imports the vendor registrations first. Future
# staff provisioning/recovery must use reviewed actions, not raw JSON secrets,
# a generic delete, or a bulk "verified email" checkbox.
for model in (EmailAddress, EmailConfirmation, Authenticator, StaffBrowserAdmission, StaffBrowserSetupGrant, StaffTOTPReplayState):
    if admin.site.is_registered(model):
        admin.site.unregister(model)


class BrowserAccessForm(forms.Form):
    user=forms.ModelChoiceField(queryset=get_user_model().objects.filter(is_active=True).order_by('username'),label='Existing staff account')
    action=forms.ChoiceField(choices=[('authorize','Allow browser access'),('invite','Send setup invitation'),
        ('suspend','Suspend browser access'),('revoke_sessions','Sign out browser sessions'),('reset_mfa','Reset MFA after identity verification')])
    reason=forms.CharField(min_length=8,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    verification_reference=forms.CharField(required=False,max_length=80,label='Identity-verification reference (MFA reset only)')


@admin.register(StaffBrowserAdmission)
class StaffBrowserAdmissionAdmin(ModelAdmin):
    list_display=('user','enabled','revision','updated_at')
    search_fields=('user__username','user__email')
    list_filter=('enabled',)
    readonly_fields=('user','subject_user_id','enabled','revision','created_at','updated_at')
    actions=None
    change_list_template='admin/staff_auth/admission_list.html'

    def has_module_permission(self,request): return request.user.is_active and request.user.is_superuser
    def has_view_permission(self,request,obj=None): return self.has_module_permission(request)
    def has_change_permission(self,request,obj=None): return False
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False

    def get_urls(self):
        return [path('manage/',self.admin_site.admin_view(self.manage),name='staff_browser_manage')]+super().get_urls()

    def manage(self,request):
        if not self.has_module_permission(request): raise PermissionDenied
        from .initial_setup import preview_setup,prepare_setup
        from .invitations import send_invitation,SubmissionError
        from .lifecycle import preview_change,apply_change
        from .setup_api import _Rejected
        form=BrowserAccessForm(request.POST or None)
        token=request.POST.get('review','')
        review=None
        error=''
        try:
            if request.method=='POST' and token:
                review=signing.loads(token,salt='staff-browser-admin-review',max_age=600)
                if review['actor_id']!=request.user.pk: raise PermissionDenied
                if review['action']=='invite':
                    receipt=prepare_setup(actor=request.user,target_user_id=review['user_id'],
                        purpose=review['purpose'],expected_revision=review['revision'],snapshot_fingerprint=review['snapshot'],
                        request_key=review['request_key'],reason=review['reason'])
                    send_invitation(actor=request.user,setup_id=receipt['setup_id'])
                    messages.success(request,'Setup invitation accepted by the email provider. Confirm receipt with the staff member.')
                else:
                    apply_change(actor=request.user,target_user_id=review['user_id'],action=review['action'],
                        expected_revision=review['revision'],request_key=review['request_key'],reason=review['reason'],
                        verification_reference=review['verification_reference'])
                    messages.success(request,'Browser access action recorded. Workflow permissions are unchanged.')
                return redirect('admin:staff_auth_staffbrowseradmission_changelist')
            if request.method=='POST' and form.is_valid():
                user=form.cleaned_data['user']
                action=form.cleaned_data['action']
                review={'actor_id':request.user.pk,'user_id':user.pk,'username':user.username,'email':user.email,
                    'action':action,'reason':form.cleaned_data['reason'],
                    'verification_reference':form.cleaned_data['verification_reference'],'request_key':uuid.uuid4().hex}
                if action=='invite':
                    purpose=StaffBrowserSetupGrant.VERIFY_EMAIL if user.has_usable_password() else StaffBrowserSetupGrant.INITIAL_PASSWORD
                    preview=preview_setup(actor=request.user,target_user_id=user.pk,purpose=purpose)
                    review.update(purpose=purpose,snapshot=preview['snapshot_fingerprint'],revision=preview['revision'])
                else:
                    preview=preview_change(actor=request.user,target_user_id=user.pk,action=action)
                    review.update(revision=preview['revision'],factors_to_remove=preview['factors_to_remove'])
                token=signing.dumps(review,salt='staff-browser-admin-review')
        except signing.BadSignature:
            review=None;error='This review expired. Review the current account before applying the action.'
        except SubmissionError as exc:
            error=('Email delivery is not confirmed. Retry this same confirmation to retain its delivery key.'
                   if exc.ambiguous or exc.retryable else 'The email provider rejected the invitation. Check the sender configuration.')
        except (ValidationError,_Rejected) as exc:
            error='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'This setup is no longer pending. Review the current staff account.'
        context={**self.admin_site.each_context(request),'title':'Manage staff browser access',
            'opts':self.model._meta,'form':form,'review':review,'review_token':token,'error':error,
            'browser_url':settings.APP_BASE_URL.rstrip('/')+'/staff/'}
        return render(request,'admin/staff_auth/manage_browser.html',context)

from django.conf import settings
from django.db import models


class CommentContext(models.Model):
    """Browser conversation metadata; CaseUpdate retains the immutable text."""

    update = models.OneToOneField('core.CaseUpdate', primary_key=True, on_delete=models.CASCADE,
        related_name='conversation_context', db_comment='Canonical complaint comment text and timestamp; context follows its case retention.')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='complaint_conversation_comments', db_comment='Canonical author; historical attribution survives account removal.')
    author_label = models.CharField(max_length=255, db_comment='Author name captured at posting, never trusted from the client.')
    affiliation = models.CharField(max_length=8, db_comment='Captured JBL, HB or IT staff affiliation.')
    reply_to = models.ForeignKey('core.CaseUpdate', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='conversation_replies', db_comment='Exact same-case parent comment being answered; child text survives parent removal.')
    payload_hash = models.CharField(max_length=64, db_comment='Hash binding a retry to text, parent, mentions and exact attachment bytes.')
    text_format = models.CharField(max_length=16, default='bold_v1', db_comment='Versioned minimal bold presentation; legacy comments remain plain text.')

    class Meta:
        db_table = 'complaints_comment_context'
        db_table_comment = 'Authoritative append-only browser staff-comment context. Retained with its owning complaint; no automatic purge.'


class CommentMention(models.Model):
    comment = models.ForeignKey(CommentContext, on_delete=models.CASCADE, related_name='mentions',
        db_comment='Comment whose explicit staff mention this records.')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='complaint_conversation_mentions', db_comment='Mentioned staff identity; never supplies case access or sends a notification.')
    user_reference = models.CharField(max_length=50, db_comment='Original staff primary key retained after governed account deletion.')
    label = models.CharField(max_length=255, db_comment='Server-captured staff name for historical mention display.')
    id = models.BigAutoField(primary_key=True, db_comment='Immutable mention-link identifier.')

    class Meta:
        db_table = 'complaints_mention_link'
        db_table_comment = 'Explicit same-case authorized staff mentions; retained with the comment, no automatic purge or outbound delivery.'
        constraints = [models.UniqueConstraint(fields=['comment', 'user_reference'], name='complaint_mention_once')]


class CommentReaction(models.Model):
    update = models.ForeignKey('core.CaseUpdate', on_delete=models.CASCADE, related_name='conversation_reactions',
        db_comment='Same-case native or historical HB comment acknowledged by this reaction.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='complaint_conversation_reactions', db_comment='Staff actor; snapshot identity survives account removal.')
    actor_reference = models.CharField(max_length=50, db_comment='Stable actor primary key used for uniqueness and retained attribution.')
    active = models.BooleanField(default=False, db_comment='Current thumbs-up state; changes retain compliance-audit receipts.')
    revision = models.PositiveBigIntegerField(default=0, db_comment='Optimistic revision preventing stale reaction requests from undoing newer actions.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Server timestamp of the latest accepted reaction state.')
    id = models.BigAutoField(primary_key=True, db_comment='Stable reaction-state identifier.')

    class Meta:
        db_table = 'complaints_reaction_state'
        db_table_comment = 'One reversible thumbs-up per staff actor and comment. Current state follows complaint retention; audit receipts remain in compliance history.'
        constraints = [models.UniqueConstraint(fields=['update', 'actor_reference'], name='complaint_reaction_actor_once')]

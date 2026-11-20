"""Check for a certificate after anything that can change a learner's result. The check runs
once the change is committed (`on_commit`), so it never holds up or rolls back the learner's own
action, and it does nothing at all for a course without a certificate switched on."""

from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.catalog.models import Activity, ContentNode
from apps.manual_sim.models import SimSubmission
from apps.progress.models import ActivityAttempt, LessonCompletion

from . import services


def _later(user_id: int, course_id: int | None) -> None:
    if course_id is not None:
        transaction.on_commit(lambda: services.evaluate_for(user_id, course_id))


@receiver(post_save, sender=ActivityAttempt, dispatch_uid="cert_after_attempt")
def _after_attempt(sender, instance: ActivityAttempt, **kwargs) -> None:
    course_id = (
        Activity.objects.filter(pk=instance.activity_id)
        .values_list("content_node__course_version__course_id", flat=True)
        .first()
    )
    _later(instance.user_id, course_id)


@receiver(post_save, sender=LessonCompletion, dispatch_uid="cert_after_lesson")
def _after_lesson(sender, instance: LessonCompletion, **kwargs) -> None:
    if instance.provisional:
        return
    course_id = (
        ContentNode.objects.filter(pk=instance.node_id)
        .values_list("course_version__course_id", flat=True)
        .first()
    )
    _later(instance.user_id, course_id)


@receiver(post_save, sender=SimSubmission, dispatch_uid="cert_after_rating")
def _after_rating(sender, instance: SimSubmission, **kwargs) -> None:
    if instance.state != SimSubmission.State.RATED:
        return
    row = (
        SimSubmission.objects.filter(pk=instance.pk)
        .values_list("case__user_id", "case__activity__content_node__course_version__course_id")
        .first()
    )
    if row:
        _later(row[0], row[1])


@receiver(post_save, sender="enrollment.VersionMove", dispatch_uid="cert_after_move")
def _after_move(sender, instance, created: bool, **kwargs) -> None:
    # Carried-over work is written with `update()`, so no other signal fires for it.
    if created:
        row = (
            type(instance)
            .objects.filter(pk=instance.pk)
            .values_list("enrollment__user_id", "enrollment__course_id")
            .first()
        )
        if row:
            _later(row[0], row[1])


@receiver(post_save, sender="enrollment.Enrollment", dispatch_uid="cert_after_enrollment")
def _after_enrollment(sender, instance, **kwargs) -> None:
    # Re-enrolling someone who had already finished.
    if instance.state == "active":
        _later(instance.user_id, instance.course_id)

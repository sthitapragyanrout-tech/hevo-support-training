from django.urls import path

from apps.bot_sim import console as practice
from apps.manual_sim import console as ratings

from . import audit_views, courses, results, roles, signins, users

app_name = "console_api"

urlpatterns = [
    # Learner results
    path("results/courses/", results.ResultCoursesView.as_view(), name="result-courses"),
    path("results/learners/", results.LearnerListView.as_view(), name="learners"),
    path("results/learners/<int:user_id>/", results.LearnerDetailView.as_view(), name="learner"),
    path(
        "results/learners/<int:user_id>/activities/<int:activity_id>/attempts/",
        results.ResetAttemptsView.as_view(),
        name="reset-attempts",
    ),
    path("results/quizzes/", results.QuizListView.as_view(), name="quizzes"),
    path("results/quizzes/<int:activity_id>/", results.QuizDetailView.as_view(), name="quiz"),
    path("results/export/", results.ResultsExportView.as_view(), name="results-export"),
    # Practice tickets: the scenario bank and transcripts
    path("practice/options/", practice.OptionsView.as_view(), name="practice-options"),
    path("practice/scenarios/", practice.ScenarioListView.as_view(), name="practice-scenarios"),
    path(
        "practice/scenarios/generate/",
        practice.GenerateView.as_view(),
        name="practice-generate",
    ),
    path(
        "practice/scenarios/<int:pk>/",
        practice.ScenarioDetailView.as_view(),
        name="practice-scenario",
    ),
    path(
        "practice/scenarios/<int:pk>/approve/",
        practice.ApproveView.as_view(),
        name="practice-approve",
    ),
    path(
        "practice/scenarios/<int:pk>/retire/", practice.RetireView.as_view(), name="practice-retire"
    ),
    path(
        "practice/scenarios/<int:pk>/restore/",
        practice.RestoreView.as_view(),
        name="practice-restore",
    ),
    path("practice/imports/", practice.ImportListView.as_view(), name="practice-imports"),
    path("practice/imports/<int:pk>/", practice.ImportDetailView.as_view(), name="practice-import"),
    path(
        "practice/imports/<int:pk>/revert/",
        practice.ImportRevertView.as_view(),
        name="practice-import-revert",
    ),
    path("practice/settings/", practice.SettingsView.as_view(), name="practice-settings"),
    path("practice/top-up/", practice.TopUpView.as_view(), name="practice-top-up"),
    path(
        "results/sessions/<int:session_id>/",
        practice.TranscriptView.as_view(),
        name="practice-session",
    ),
    # Mentor-rated simulations: the review queue and the trainer's actions on a case
    path("ratings/queue/", ratings.QueueView.as_view(), name="ratings-queue"),
    path("ratings/mentors/", ratings.MentorsView.as_view(), name="ratings-mentors"),
    path("ratings/stats/", ratings.StatsView.as_view(), name="ratings-stats"),
    path("ratings/submissions/<int:pk>/", ratings.ThreadView.as_view(), name="ratings-thread"),
    path("ratings/submissions/<int:pk>/claim/", ratings.ClaimView.as_view(), name="ratings-claim"),
    path(
        "ratings/submissions/<int:pk>/release/",
        ratings.ReleaseView.as_view(),
        name="ratings-release",
    ),
    path(
        "ratings/submissions/<int:pk>/reassign/",
        ratings.ReassignView.as_view(),
        name="ratings-reassign",
    ),
    path("ratings/submissions/<int:pk>/draft/", ratings.DraftView.as_view(), name="ratings-draft"),
    path("ratings/submissions/<int:pk>/rate/", ratings.RateView.as_view(), name="ratings-rate"),
    path(
        "ratings/cases/<int:case_id>/extend/", ratings.ExtendView.as_view(), name="ratings-extend"
    ),
    path("ratings/cases/<int:case_id>/waive/", ratings.WaiveView.as_view(), name="ratings-waive"),
    path("ratings/cases/<int:case_id>/close/", ratings.CloseView.as_view(), name="ratings-close"),
    path(
        "ratings/cases/<int:case_id>/reopen/", ratings.ReopenView.as_view(), name="ratings-reopen"
    ),
    # Courses back-office
    path("courses/", courses.CourseListView.as_view(), name="courses"),
    path("courses/<int:course_id>/", courses.CourseDetailView.as_view(), name="course"),
    path(
        "courses/<int:course_id>/archive/",
        courses.CourseArchiveView.as_view(),
        name="course-archive",
    ),
    path(
        "courses/<int:course_id>/restore/",
        courses.CourseRestoreView.as_view(),
        name="course-restore",
    ),
    # Users and roles
    path("users/", users.UserListView.as_view(), name="users"),
    path("users/<int:user_id>/", users.UserDetailView.as_view(), name="user"),
    path("users/<int:user_id>/set-password/", users.SetPasswordView.as_view(), name="set-password"),
    path("users/<int:user_id>/unlock/", users.UnlockView.as_view(), name="unlock"),
    path("users/<int:user_id>/roles/", users.UserRolesView.as_view(), name="user-roles"),
    path("roles/", roles.RoleListView.as_view(), name="roles"),
    path("roles/new/", roles.RoleCreateView.as_view(), name="role-create"),
    path("roles/options/", roles.RoleOptionsView.as_view(), name="role-options"),
    path("roles/<int:role_id>/", roles.RoleDetailView.as_view(), name="role"),
    path(
        "roles/<int:role_id>/permissions/",
        roles.RolePermissionsView.as_view(),
        name="role-permissions",
    ),
    path("signins/", signins.SignInListView.as_view(), name="signins"),
    # Audit log
    path("audit/", audit_views.AuditListView.as_view(), name="audit"),
    path("audit/actions/", audit_views.AuditActionsView.as_view(), name="audit-actions"),
]

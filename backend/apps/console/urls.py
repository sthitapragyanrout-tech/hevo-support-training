from django.urls import path

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

import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom'

import { AppShell } from './app/AppShell'
import { PageState } from './components/PageState'
import { ProtectedRoute } from './app/ProtectedRoute'
import { LoginPage } from './features/auth/LoginPage'
import { CourseLandingPage } from './features/catalog/CourseLandingPage'
import { CourseLayout } from './features/catalog/CourseLayout'
import { CourseListPage } from './features/catalog/CourseListPage'
import { CourseRoute } from './features/catalog/CourseRoute'
import { LessonPage } from './features/catalog/LessonPage'
import { ChangePasswordPage } from './features/account/ChangePasswordPage'
import { AdminIndex, AdminLayout } from './features/admin/AdminLayout'
import { AuditPage } from './features/admin/AuditPage'
import { CourseDetailPage } from './features/admin/CourseDetailPage'
import { CoursesPage } from './features/admin/CoursesPage'
import { LearnerDetailPage } from './features/admin/LearnerDetailPage'
import { DashboardPage } from './features/admin/DashboardPage'
import { EnrollmentsPage } from './features/admin/EnrollmentsPage'
import { PracticeScenariosPage } from './features/admin/PracticeScenariosPage'
import { ProgramsPage } from './features/admin/ProgramsPage'
import { QuizReviewPage } from './features/admin/QuizReviewPage'
import { RatingPage } from './features/admin/RatingPage'
import { ProgressPage } from './features/catalog/ProgressPage'
import { CertificatePage } from './features/certificates/CertificatePage'
import { NotificationsPage } from './features/notifications/NotificationsPage'
import { RatingsPage } from './features/admin/RatingsPage'
import { QuizDetailPage } from './features/admin/QuizDetailPage'
import { QuizzesPage } from './features/admin/QuizzesPage'
import { RolesPage } from './features/admin/RolesPage'
import { SignInsPage } from './features/admin/SignInsPage'
import { SimTranscriptPage } from './features/admin/SimTranscriptPage'
import { UserDetailPage } from './features/admin/UserDetailPage'
import { UsersPage } from './features/admin/UsersPage'
import { CourseBuilderPage } from './features/studio/CourseBuilderPage'
import { CreateCoursePage } from './features/studio/CreateCoursePage'
import { CurriculumTab } from './features/studio/CurriculumTab'
import { ImportTab } from './features/studio/ImportTab'
import { OverviewTab } from './features/studio/OverviewTab'
import { SettingsTab } from './features/studio/SettingsTab'
import { StudioCourseList } from './features/studio/StudioCourseList'
import { StudioPreviewRoute } from './features/studio/StudioPreviewRoute'
import { RequireCapability } from './lib/capabilities'
import { CAN } from './lib/capabilityKeys'

/** Anyone holding one of these gets the console (and sees what they may open). */
const CONSOLE_ACTIONS = [
  CAN.viewResults,
  CAN.viewAudit,
  CAN.manageUsers,
  CAN.manageRoles,
  CAN.authorContent,
  CAN.publishCourse,
  CAN.rateSimulations,
  CAN.manageReviews,
  CAN.manageEnrollments,
]

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<CourseListPage />} />
        <Route path="/progress" element={<ProgressPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/certificates/:code" element={<CertificatePage />} />
        <Route path="/account/password" element={<ChangePasswordPage />} />
        {/* CourseRoute loads the tree once for both the landing and lesson views. */}
        <Route path="/courses/:courseId" element={<CourseRoute />}>
          <Route index element={<CourseLandingPage />} />
          <Route element={<CourseLayout />}>
            <Route path="lessons/:nodeId" element={<LessonPage />} />
          </Route>
        </Route>

        {/* Admin Console: whatever the server says this person may manage. */}
        <Route
          path="/admin"
          element={
            <RequireCapability any={CONSOLE_ACTIONS}>
              <AdminLayout />
            </RequireCapability>
          }
        >
          <Route index element={<AdminIndex />} />
          <Route
            path="results"
            element={
              <RequireCapability action={CAN.viewResults}>
                <Outlet />
              </RequireCapability>
            }
          >
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={<DashboardPage />} />
            {/* The Dashboard replaced the old Learners list. */}
            <Route path="learners" element={<Navigate to="/admin/results/dashboard" replace />} />
            <Route path="learners/:userId" element={<LearnerDetailPage />} />
            <Route path="quizzes" element={<QuizzesPage />} />
            <Route path="quizzes/:activityId" element={<QuizDetailPage />} />
            <Route path="sessions/:sessionId" element={<SimTranscriptPage />} />
          </Route>
          <Route
            path="courses"
            element={
              <RequireCapability any={[CAN.authorContent, CAN.publishCourse]}>
                <Outlet />
              </RequireCapability>
            }
          >
            <Route index element={<CoursesPage />} />
            <Route path=":courseId" element={<CourseDetailPage />} />
          </Route>
          <Route
            path="ratings"
            element={
              <RequireCapability any={[CAN.rateSimulations, CAN.manageReviews]}>
                <Outlet />
              </RequireCapability>
            }
          >
            <Route index element={<RatingsPage />} />
            <Route path="quiz/:reviewId" element={<QuizReviewPage />} />
            <Route path=":submissionId" element={<RatingPage />} />
          </Route>
          <Route
            path="practice"
            element={
              <RequireCapability any={[CAN.authorContent, CAN.publishCourse]}>
                <Outlet />
              </RequireCapability>
            }
          >
            <Route index element={<PracticeScenariosPage />} />
          </Route>
          <Route
            path="enrollments"
            element={
              <RequireCapability action={CAN.manageEnrollments}>
                <Outlet />
              </RequireCapability>
            }
          >
            <Route index element={<EnrollmentsPage />} />
          </Route>
          <Route
            path="programs"
            element={
              <RequireCapability action={CAN.manageEnrollments}>
                <Outlet />
              </RequireCapability>
            }
          >
            <Route index element={<ProgramsPage />} />
          </Route>
          <Route
            path="users"
            element={
              <RequireCapability action={CAN.manageUsers}>
                <Outlet />
              </RequireCapability>
            }
          >
            <Route index element={<UsersPage />} />
            <Route path=":userId" element={<UserDetailPage />} />
          </Route>
          <Route
            path="signins"
            element={
              <RequireCapability action={CAN.manageUsers}>
                <SignInsPage />
              </RequireCapability>
            }
          />
          <Route
            path="roles"
            element={
              <RequireCapability action={CAN.manageRoles}>
                <RolesPage />
              </RequireCapability>
            }
          />
          <Route
            path="audit"
            element={
              <RequireCapability action={CAN.viewAudit}>
                <AuditPage />
              </RequireCapability>
            }
          />
        </Route>

        {/* Studio: authoring for anyone the server says may author content. */}
        <Route
          path="/studio"
          element={
            <RequireCapability action={CAN.authorContent}>
              <Outlet />
            </RequireCapability>
          }
        >
          <Route index element={<StudioCourseList />} />
          <Route path="new" element={<CreateCoursePage />} />
          <Route path="courses/:courseId" element={<CourseBuilderPage />}>
            <Route index element={<Navigate to="curriculum" replace />} />
            <Route path="overview" element={<OverviewTab />} />
            <Route path="curriculum" element={<CurriculumTab />} />
            <Route path="curriculum/:nodeId" element={<CurriculumTab />} />
            <Route path="import" element={<ImportTab />} />
            <Route path="settings" element={<SettingsTab />} />
          </Route>
          {/* The learner screens, fed with the draft. */}
          <Route path="courses/:courseId/preview" element={<StudioPreviewRoute />}>
            <Route index element={<CourseLandingPage />} />
            <Route element={<CourseLayout />}>
              <Route path="lessons/:nodeId" element={<LessonPage />} />
            </Route>
          </Route>
        </Route>

        {/* Anything else: say so, instead of leaving the page blank. */}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

function NotFound() {
  return (
    <PageState kind="empty" title="We can’t find that page">
      It may have moved, or the link may be wrong. <Link to="/">Back to My courses</Link>
    </PageState>
  )
}

export default App

import { Navigate, Outlet, Route, Routes } from 'react-router-dom'

import { AppShell } from './app/AppShell'
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
import { LearnersPage } from './features/admin/LearnersPage'
import { QuizDetailPage } from './features/admin/QuizDetailPage'
import { QuizzesPage } from './features/admin/QuizzesPage'
import { RolesPage } from './features/admin/RolesPage'
import { SignInsPage } from './features/admin/SignInsPage'
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
            <Route index element={<Navigate to="learners" replace />} />
            <Route path="learners" element={<LearnersPage />} />
            <Route path="learners/:userId" element={<LearnerDetailPage />} />
            <Route path="quizzes" element={<QuizzesPage />} />
            <Route path="quizzes/:activityId" element={<QuizDetailPage />} />
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
      </Route>
    </Routes>
  )
}

export default App

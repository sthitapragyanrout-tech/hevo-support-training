import { Link } from 'react-router-dom'

import { AdminPage } from './AdminPage'

/** A placeholder: the dashboard of every learner's performance and scores is still to be
 * designed. It shows no numbers on purpose — a tile that said 0 would read as a result. */
export function DashboardPage() {
  return (
    <AdminPage eyebrow="Results" title="Dashboard" hint="A view of how every learner is doing, with all their scores.">
      <p>
        <strong>Not built yet.</strong> This is where the overall picture will go. Until then, the detail is
        already available:
      </p>
      <ul>
        <li>
          <Link to="/admin/results/learners">Learners</Link> — each person’s progress and scores, with a CSV export.
        </li>
        <li>
          <Link to="/admin/results/quizzes">Quizzes</Link> — how everyone did on each quiz.
        </li>
      </ul>
    </AdminPage>
  )
}

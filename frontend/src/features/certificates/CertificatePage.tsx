import { Link, useParams } from 'react-router-dom'

import { Logo } from '../../components/Logo'
import { PageState } from '../../components/PageState'
import { certificatesApi } from '../../lib/api'
import { useAsync } from '../catalog/useAsync'
import styles from './CertificatePage.module.css'

const longDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })

/** A certificate, laid out to print (or save as PDF from the print dialog) on one A4 page. */
export function CertificatePage() {
  const { code = '' } = useParams()
  const { data, loading, error, reload } = useAsync(() => certificatesApi.get(code), code)

  if (loading) return <PageState kind="loading" />
  if (error || !data) {
    return (
      <PageState kind="error" title="Certificate not found" onRetry={reload}>
        It may have been revoked, or the link is wrong.
      </PageState>
    )
  }

  return (
    <div className={`page ${styles.wrap}`}>
      <div className={styles.toolbar}>
        <Link to="/progress" className="btn">
          My progress
        </Link>
        <button type="button" className="btn btn-primary" onClick={() => window.print()}>
          Print or save as PDF
        </button>
      </div>
      {data.revoked && (
        <p className={styles.revoked} role="status">
          This certificate has been revoked.
        </p>
      )}
      <article className={styles.sheet} aria-label="Certificate">
        <div className={styles.brand}>
          <Logo size={28} />
          <span>Hevo Support Training</span>
        </div>
        <p className={styles.kicker}>Certificate of completion</p>
        <p className={styles.presented}>This certifies that</p>
        <h1 className={styles.name}>{data.name}</h1>
        {data.employee_id && <p className={styles.emp}>Employee ID {data.employee_id}</p>}
        <p className={styles.presented}>has successfully completed</p>
        <h2 className={styles.course}>{data.course_title}</h2>
        <dl className={styles.facts}>
          <div>
            <dt>Date</dt>
            <dd>{longDate(data.issued_at)}</dd>
          </div>
          <div>
            <dt>Course score</dt>
            <dd>
              {data.score === null
                ? 'Completed'
                : `${Math.round(data.score * 100)}% (pass mark ${data.threshold}%)`}
            </dd>
          </div>
          <div>
            <dt>Certificate ID</dt>
            <dd className={styles.code}>{data.code}</dd>
          </div>
        </dl>
      </article>
    </div>
  )
}

import { Link, useParams } from 'react-router-dom'

import { CourseRouteBase } from '../catalog/CourseRoute'
import styles from './StudioPreviewRoute.module.css'
import { studioApi } from './studioApi'

function PreviewBanner({ courseId }: { courseId: string }) {
  return (
    <div className={styles.banner} role="status">
      <p>
        <span className={styles.tag}>Preview</span>
        <strong>Previewing the draft.</strong> This is exactly what learners will see once it’s
        published — they can’t see it yet.
      </p>
      <Link to={`/studio/courses/${courseId}/curriculum`} className="btn btn-sm">
        Back to the builder
      </Link>
    </div>
  )
}

/** The learner course experience, fed with the author's draft. Same screens,
 * same components — only the data source and the link prefix differ. */
export function StudioPreviewRoute() {
  const { courseId = '' } = useParams()
  return (
    <CourseRouteBase
      load={(id) => studioApi.preview(id)}
      basePathFor={(id) => `/studio/courses/${id}/preview`}
      preview
      banner={<PreviewBanner courseId={courseId} />}
      backTo={{ to: `/studio/courses/${courseId}/curriculum`, label: 'Back to the builder' }}
    />
  )
}

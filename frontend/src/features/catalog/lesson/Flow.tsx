import styles from './Flow.module.css'
import type { FlowStep } from './parseFlow'

export function Flow({ steps }: { steps: FlowStep[] }) {
  const summary = steps.map((s) => s.label).join(', then ')
  return (
    <figure className={styles.figure} role="group" aria-label={`Flow: ${summary}`}>
      <ol className={styles.flow}>
        {steps.map((step, i) => (
          <li
            key={i}
            className={`${styles.step} ${step.highlight ? styles.highlight : ''}`}
            aria-current={step.highlight ? 'step' : undefined}
          >
            {step.label}
          </li>
        ))}
      </ol>
    </figure>
  )
}

import type { NodeKind, TreeNode } from '../../lib/api'

function node(
  id: number,
  kind: NodeKind,
  title: string,
  extra: Partial<TreeNode> = {},
  children: TreeNode[] = [],
): TreeNode {
  return {
    id,
    kind,
    title,
    slug: title.toLowerCase(),
    description: '',
    is_required: true,
    estimated_minutes: null,
    activities: [],
    children,
    ...extra,
  }
}

/** Course → 2 modules → 2 lessons → 3 sections. Learner terms:
 *  Module 1 "Fundamentals": Lesson "Pipelines" (sections Sources, Ingestion)
 *  Module 2 "Troubleshooting": Lesson "Failures" (section Logs).
 *  45 minutes in total (33 + 12). */
/** What a learner is sent for the sample quiz: questions and choices only. */
export const SAMPLE_QUESTIONS = [
  { text: 'Where does a pipeline read its data from?', choices: ['A source', 'A destination'], multiple: false },
  {
    text: 'Which of these are load modes?',
    choices: ['Full load', 'Incremental', 'Reverse'],
    multiple: true,
  },
]

export const sampleCourse: TreeNode = node(
  1,
  'course',
  'CX Onboarding',
  {
    description:
      'Learn the platform.\n\n## What you’ll learn\n\n- Place a problem\n- Read a log',
  },
  [
    node(2, 'segment', 'Fundamentals', { description: 'The basics.' }, [
      node(3, 'topic', 'Pipelines', { description: 'How data flows from A to B.' }, [
        node(4, 'subtopic', 'Sources', {
          description:
            '### What is a source?\n\nWhere data starts.\n\n<script>alert(1)</script>\n\n<b>raw html</b>',
          estimated_minutes: 15,
          activities: [
            {
              id: 1,
              activity_type: 'reading',
              title: 'Read the docs',
              is_required: true,
              points: 0,
              order: 0,
              max_attempts: 3,
              config: { source_url: 'https://docs.example.com/sources', estimated_read_minutes: 8 },
              completable: true,
            },
            {
              id: 2,
              activity_type: 'mcq',
              title: 'Sources quiz',
              // Optional here so most flows only need the reading; quiz tests
              // make it required (see `quizRequired` in testApi).
              is_required: false,
              points: 0,
              order: 1,
              max_attempts: 3,
              config: { questions: SAMPLE_QUESTIONS, pass_threshold: 0.5 },
              completable: true,
            },
          ],
        }),
        node(5, 'subtopic', 'Ingestion', {
          description: 'Full load, incremental and CDC.',
          estimated_minutes: 18,
          activities: [
            {
              id: 3,
              activity_type: 'video',
              title: 'Ingestion walkthrough',
              is_required: true,
              points: 0,
              order: 0,
              max_attempts: 3,
              config: {},
              completable: false,
            },
          ],
        }),
      ]),
    ]),
    node(6, 'segment', 'Troubleshooting', {}, [
      node(7, 'topic', 'Failures', { description: 'Read the evidence before you guess.' }, [
        node(8, 'subtopic', 'Logs', { description: 'Read logs.', estimated_minutes: 12 }),
      ]),
    ]),
  ],
)

import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { ReactNode } from 'react'

import { Icon } from '../../components/Icon'
import styles from './SortableList.module.css'

interface Item {
  id: number
}

interface Props<T extends Item> {
  items: T[]
  /** Called with the full new id order after a drop. */
  onReorder: (ids: number[]) => void
  disabled?: boolean
  /** Accessible name for one item's drag handle. */
  handleLabel: (item: T) => string
  children: (item: T, index: number) => ReactNode
}

/** A vertical, keyboard-accessible sortable list (sibling reorder only).
 * Pointer: drag the grip. Keyboard: focus the grip, Space to lift, arrows to
 * move, Space to drop, Esc to cancel. */
export function SortableList<T extends Item>({
  items,
  onReorder,
  disabled,
  handleLabel,
  children,
}: Props<T>) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  function onDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return
    const from = items.findIndex((i) => i.id === active.id)
    const to = items.findIndex((i) => i.id === over.id)
    if (from < 0 || to < 0) return
    onReorder(arrayMove(items, from, to).map((i) => i.id))
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={items.map((i) => i.id)} strategy={verticalListSortingStrategy}>
        <ul className={styles.list}>
          {items.map((item, index) => (
            <SortableRow key={item.id} id={item.id} disabled={disabled} label={handleLabel(item)}>
              {children(item, index)}
            </SortableRow>
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  )
}

function SortableRow({
  id,
  disabled,
  label,
  children,
}: {
  id: number
  disabled?: boolean
  label: string
  children: ReactNode
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id, disabled })

  return (
    <li
      ref={setNodeRef}
      className={`${styles.item} ${isDragging ? styles.dragging : ''}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      {!disabled && (
        <button
          type="button"
          ref={setActivatorNodeRef}
          className={styles.handle}
          aria-label={`Reorder ${label}`}
          {...attributes}
          {...listeners}
        >
          <Icon name="grip" size={14} />
        </button>
      )}
      <div className={styles.content}>{children}</div>
    </li>
  )
}

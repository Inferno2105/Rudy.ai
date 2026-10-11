import { Compass } from 'lucide-react'
import { Link } from 'react-router'

import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/feedback'
import { useDocumentTitle } from '../lib/utils'

export function NotFoundPage() {
  useDocumentTitle('Not found')
  return (
    <EmptyState
      icon={<Compass />}
      title="Page not found"
      action={
        <Button asChild variant="primary">
          <Link to="/meetings">Go to meetings</Link>
        </Button>
      }
    >
      There is nothing at this address.
    </EmptyState>
  )
}

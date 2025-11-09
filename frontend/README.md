# re-ink Frontend

React frontend for the re-ink reinsurance contract management system.

## Features

- **Document Upload**: Drag-and-drop interface for uploading contracts
- **Extraction Monitoring**: Real-time status updates for AI extraction
- **Review Interface**: Review and edit extracted contract data
- **Contract Dashboard**: View and manage all contracts
- **Party Management**: Browse and search parties
- **Modern UI**: Clean, professional enterprise design

## Setup

### Prerequisites

- Node.js 18+
- npm or yarn

### Installation

1. Install dependencies:
```bash
npm install
```

2. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

### Running the Development Server

```bash
npm run dev
```

The application will be available at http://localhost:3000

### Building for Production

```bash
npm run build
```

Preview production build:
```bash
npm run preview
```

## Project Structure

```
frontend/
├── src/
│   ├── components/       # Reusable React components
│   ├── pages/            # Page components
│   ├── services/         # API service layer
│   ├── types/            # TypeScript type definitions
│   ├── styles/           # CSS styles
│   ├── App.tsx           # Main application component
│   └── main.tsx          # Application entry point
├── public/               # Static assets
├── index.html            # HTML template
└── package.json          # Dependencies
```

## Technology Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **React Router** - Client-side routing
- **React Query** - Server state management
- **Axios** - HTTP client
- **React Hook Form** - Form handling
- **Lucide React** - Icon library
- **Vite** - Build tool

## Key Components

### FileUpload
Handles document upload with drag-and-drop support, file validation, and progress tracking.

### ExtractionStatus
Displays extraction status with polling for real-time updates.

### ReviewForm
Allows users to review and edit AI-extracted contract and party data before creating records.

### Dashboard
Main landing page showing contracts and parties overview with quick stats.

### ContractsPage
List view of all contracts with filtering and search capabilities.

### PartiesPage
Grid view of all parties with filtering and search capabilities.

## API Integration

The frontend communicates with the backend API through the service layer in `src/services/api.ts`.

All API calls use axios with the base URL configured via environment variables.

## Styling

The application uses custom CSS with CSS variables for theming. The design follows enterprise software best practices with:

- Clean, professional aesthetics
- Consistent spacing and typography
- Accessible color contrast
- Responsive layouts
- Smooth transitions and animations

## Development

### Type Safety

The project uses TypeScript for full type safety. All API types are defined in `src/types/index.ts`.

### Code Organization

- Components are organized by feature
- Shared types are in `src/types/`
- API calls are centralized in `src/services/`
- Pages handle routing and layout
- Reusable components are in `src/components/`

### Linting

```bash
npm run lint
```

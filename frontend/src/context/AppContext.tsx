import { createContext, useCallback, useContext, useReducer } from 'react';
import type { ReactNode } from 'react';
import type { Batch } from '../api';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

type AppView = 'workbench' | 'settings' | 'archive';

interface AppState {
  selectedBatch: Batch | null;
  currentView: AppView;
  refreshKey: number;
}

const initialState: AppState = {
  selectedBatch: null,
  currentView: 'workbench',
  refreshKey: 0,
};

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

type AppAction =
  | { type: 'SELECT_BATCH'; batch: Batch | null }
  | { type: 'SET_VIEW'; view: AppView }
  | { type: 'NEW_TASK' }
  | { type: 'REFRESH' }
  | { type: 'BATCH_UPDATED'; batch: Batch };

function reducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SELECT_BATCH':
      return { ...state, selectedBatch: action.batch, currentView: 'workbench' };
    case 'SET_VIEW':
      return { ...state, currentView: action.view };
    case 'NEW_TASK':
      return { ...state, selectedBatch: null, currentView: 'workbench' };
    case 'REFRESH':
      return { ...state, refreshKey: state.refreshKey + 1 };
    case 'BATCH_UPDATED':
      return { ...state, selectedBatch: action.batch };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface AppContextValue {
  state: AppState;
  selectBatch: (batch: Batch | null) => void;
  setView: (view: AppView) => void;
  newTask: () => void;
  refresh: () => void;
  batchUpdated: (batch: Batch) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const selectBatch = useCallback((batch: Batch | null) => dispatch({ type: 'SELECT_BATCH', batch }), []);
  const setView = useCallback((view: AppView) => dispatch({ type: 'SET_VIEW', view }), []);
  const newTask = useCallback(() => dispatch({ type: 'NEW_TASK' }), []);
  const refresh = useCallback(() => dispatch({ type: 'REFRESH' }), []);
  const batchUpdated = useCallback((batch: Batch) => dispatch({ type: 'BATCH_UPDATED', batch }), []);

  return (
    <AppContext.Provider value={{ state, selectBatch, setView, newTask, refresh, batchUpdated }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>');
  return ctx;
}

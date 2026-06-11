import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider } from './context/AppContext';
import MainLayout from './layouts/MainLayout';
import Dashboard from './pages/Dashboard';
import Archive from './pages/Archive';
import TaskList from './pages/TaskList';
import TaskNew from './pages/TaskNew';
import TaskDetail from './pages/TaskDetail';
import Integrations from './pages/Integrations';
import Settings from './pages/Settings';

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="rules" element={<Archive />} />
            <Route path="tasks" element={<TaskList />} />
            <Route path="tasks/new" element={<TaskNew />} />
            <Route path="tasks/:batchId" element={<TaskDetail />} />
            <Route path="integrations" element={<Integrations />} />
            <Route path="settings" element={<Settings />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}

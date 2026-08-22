import type React from 'react';
import { BrowserRouter as Router, Navigate, Route, Routes } from 'react-router-dom';
import BacktestPage from './pages/BacktestPage';
import { Shell } from './components/common';
import './App.css';

const AppContent: React.FC = () => {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/" element={<Navigate to="/backtest" replace />} />
        <Route path="*" element={<Navigate to="/backtest" replace />} />
      </Route>
    </Routes>
  );
};

const App: React.FC = () => {
  return (
    <Router>
      <AppContent />
    </Router>
  );
};

export default App;

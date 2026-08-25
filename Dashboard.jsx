import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Activity, Cpu, ShieldCheck, DollarSign, TrendingUp, Users, Zap, Globe } from 'lucide-react';
import { toast } from 'react-hot-toast';

const API_URL = process.env.REACT_APP_API_URL || 'https://dein-name.up.railway.app';

export default function Dashboard() {
  const [activeAgents, setActiveAgents] = useState([]);
  const [stats, setStats] = useState({
    revenue: 0,
    activeSparten: 0,
    wallet: 0,
    level: 'Level 1',
    uptime: '99.9%',
    leads: 0,
  });
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);

  // Daten laden
  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      
      // Health-Check & Sparten
      const [healthRes, spartenRes] = await Promise.all([
        axios.get(`${API_URL}/api/revenue/health`),
        axios.get(`${API_URL}/api/revenue/sparten/alle`),
      ]);

      const health = healthRes.data;
      
      setStats({
        revenue: health?.total_bank_earnings_usd || 0,
        activeSparten: health?.sparten_anzahl || 0,
        wallet: health?.wallet_balance_usd || 0,
        level: health?.level || 'Level 1',
        uptime: health?.uptime || '99.9%',
        leads: 0, // Kann später aus Lead-Bot kommen
      });

      // Simulierte Aktivitäten (später durch echte ersetzen)
      setActivities([
        { time: '14:32', message: 'Excel-Import: 25 Leads geladen', type: 'success' },
        { time: '14:15', message: 'YouTube Promotion gestartet', type: 'info' },
        { time: '13:50', message: 'Rechnung #INV-7890 bezahlt (750 €)', type: 'success' },
        { time: '13:20', message: 'Lead-Gen: 12 neue Leads gefunden', type: 'warning' },
      ]);

      setLoading(false);
    } catch (error) {
      console.error('Fehler beim Laden:', error);
      toast.error('Fehler beim Laden des Dashboards');
      setLoading(false);
    }
  };

  // Status-Farben
  const statusColors = {
    success: 'bg-green-100 text-green-800',
    warning: 'bg-yellow-100 text-yellow-800',
    error: 'bg-red-100 text-red-800',
    info: 'bg-blue-100 text-blue-800',
  };

  // Statistik-Karte
  const StatCard = ({ title, value, icon, color, change }) => (
    <div className="bg-white rounded-xl shadow-lg p-6 transition-all hover:shadow-xl hover:scale-[1.01]">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-gray-500 text-sm font-medium">{title}</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">
            {typeof value === 'number' ? value.toLocaleString('de-DE') : value}
          </p>
          {change && (
            <p className={`text-sm ${change > 0 ? 'text-green-500' : 'text-red-500'} mt-1`}>
              {change > 0 ? '↑' : '↓'} {Math.abs(change)}%
            </p>
          )}
        </div>
        <div className={`p-3 rounded-full ${color}`}>
          {icon}
        </div>
      </div>
    </div>
  );

  // Aktivitätseintrag
  const ActivityItem = ({ time, message, type }) => (
    <div className="flex items-center gap-4 py-3 border-b border-gray-100 last:border-0">
      <div className={`px-3 py-1 rounded-full text-xs font-medium ${statusColors[type] || statusColors.info}`}>
        {type?.toUpperCase() || 'INFO'}
      </div>
      <div className="flex-1">
        <p className="text-gray-800 text-sm">{message}</p>
      </div>
      <div className="text-gray-400 text-xs">{time}</div>
    </div>
  );

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-2">
              🚀 RevenueAgentRoute
            </h1>
            <p className="text-gray-500 text-sm">Global Command Center – 24/7 autonom</p>
          </div>
          <div className="flex gap-3 flex-wrap">
            <button 
              onClick={fetchDashboardData}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition flex items-center gap-2"
            >
              <Zap className="w-4 h-4" /> Aktualisieren
            </button>
            <div className="flex items-center gap-2 bg-green-100 px-4 py-2 rounded-lg">
              <div className="w-3 h-3 rounded-full bg-green-500 animate-pulse"></div>
              <span className="text-green-800 text-sm font-medium">Live</span>
            </div>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
          <StatCard 
            title="Umsatz" 
            value={stats.revenue} 
            icon={<DollarSign className="w-6 h-6 text-green-600" />}
            color="bg-green-100" 
            change={35} 
          />
          <StatCard 
            title="Aktive Sparten" 
            value={stats.activeSparten} 
            icon={<Activity className="w-6 h-6 text-blue-600" />}
            color="bg-blue-100" 
          />
          <StatCard 
            title="Wallet" 
            value={stats.wallet} 
            icon={<ShieldCheck className="w-6 h-6 text-yellow-600" />}
            color="bg-yellow-100" 
            change={200} 
          />
          <StatCard 
            title="Leads" 
            value={stats.leads} 
            icon={<Users className="w-6 h-6 text-purple-600" />}
            color="bg-purple-100" 
            change={12} 
          />
        </div>

        {/* Level & Region */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div className="bg-white rounded-xl shadow-lg p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">📊 System Level</h3>
            <p className="text-3xl font-bold text-blue-600">{stats.level}</p>
            <p className="text-gray-500 text-sm mt-1">Uptime: {stats.uptime}</p>
            <div className="mt-4 flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-green-500"></div>
              <span className="text-sm text-gray-600">Alle Systeme online</span>
            </div>
          </div>
          <div className="bg-white rounded-xl shadow-lg p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">🌍 Global Command Center</h3>
            <div className="grid grid-cols-3 gap-4">
              <div className="text-center p-3 bg-green-50 rounded-lg">
                <div className="w-3 h-3 mx-auto rounded-full bg-green-500"></div>
                <p className="text-sm font-medium mt-2">🇺🇸 USA</p>
                <p className="text-xs text-gray-500">Active</p>
              </div>
              <div className="text-center p-3 bg-green-50 rounded-lg">
                <div className="w-3 h-3 mx-auto rounded-full bg-green-500"></div>
                <p className="text-sm font-medium mt-2">🇪🇺 Europa</p>
                <p className="text-xs text-gray-500">Active</p>
              </div>
              <div className="text-center p-3 bg-yellow-50 rounded-lg">
                <div className="w-3 h-3 mx-auto rounded-full bg-yellow-500"></div>
                <p className="text-sm font-medium mt-2">🇯🇵 Asien</p>
                <p className="text-xs text-gray-500">Standby</p>
              </div>
            </div>
          </div>
        </div>

        {/* Activities */}
        <div className="bg-white rounded-xl shadow-lg p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Activity className="w-5 h-5 text-gray-600" /> Letzte Aktivitäten
          </h3>
          <div>
            {activities.length > 0 ? (
              activities.map((item, index) => (
                <ActivityItem key={index} {...item} />
              ))
            ) : (
              <p className="text-gray-500 text-center py-8">Keine Aktivitäten vorhanden</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
                }

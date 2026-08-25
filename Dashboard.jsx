import React, { useState } from 'react';
import { Activity, Cpu, ShieldCheck, DollarSign, Terminal } from 'lucide-react';

export default function Dashboard() {
  const [activeAgents, setActiveAgents] = useState(70);

  return (
    <div className="min-h-screen bg-slate-950 text-cyan-400 p-6 font-mono">
      <header className="flex justify-between items-center border-b border-cyan-800 pb-4 mb-6">
        <h1 className="text-2xl font-bold tracking-wider">REVENUE AGENT ROUTE // COMMAND CENTER</h1>
        <span className="flex items-center gap-2 text-green-400 text-sm">
          <span className="w-3 h-3 bg-green-500 rounded-full animate-pulse"></span> SYSTEM ONLINE
        </span>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-slate-900 border border-cyan-900 p-4 rounded-lg shadow-lg">
          <div className="flex justify-between items-center text-slate-400 mb-2">
            <span>Aktive Sparten</span>
            <Cpu className="text-cyan-400" />
          </div>
          <p className="text-3xl font-bold text-white">{activeAgents}+ B2B</p>
        </div>

        <div className="bg-slate-900 border border-cyan-900 p-4 rounded-lg shadow-lg">
          <div className="flex justify-between items-center text-slate-400 mb-2">
            <span>Self-Evolution</span>
            <Activity className="text-cyan-400" />
          </div>
          <p className="text-3xl font-bold text-green-400">Aktiv</p>
        </div>

        <div className="bg-slate-900 border border-cyan-900 p-4 rounded-lg shadow-lg">
          <div className="flex justify-between items-center text-slate-400 mb-2">
            <span>Autonomer Modus</span>
            <DollarSign className="text-cyan-400" />
          </div>
          <p className="text-3xl font-bold text-white">0€ Start</p>
        </div>

        <div className="bg-slate-900 border border-cyan-900 p-4 rounded-lg shadow-lg">
          <div className="flex justify-between items-center text-slate-400 mb-2">
            <span>Security</span>
            <ShieldCheck className="text-cyan-400" />
          </div>
          <p className="text-3xl font-bold text-purple-400">ISO Ready</p>
        </div>
      </div>

      <div className="bg-slate-900 border border-cyan-900 p-6 rounded-lg shadow-lg">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Terminal size={20} /> Live System Logs & Agenten-Status
        </h2>
        <div className="bg-black p-4 rounded text-sm text-green-500 h-48 overflow-y-auto">
          <p>[INFO] Self-Evolution Engine gestartet...</p>
          <p>[SUCCESS] 70+ B2B-Sparten erfolgreich synchronisiert.</p>
          <p>[AUTONOMOUS] Generiere neue Leads und optimiere Code...</p>
        </div>
      </div>
    </div>
  );
}

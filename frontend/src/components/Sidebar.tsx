import { 
  FileDown, 
  Terminal, 
  SlidersHorizontal, 
  SendToBack, 
  CheckCircle, 
  AlertTriangle,
  FlameKindling
} from 'lucide-react';
import { TaskStatus } from '../types';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  status: TaskStatus;
  currentStep: string;
}

export default function Sidebar({ activeTab, setActiveTab, status, currentStep }: SidebarProps) {
  const tabs = [
    {
      id: 'import',
      name: 'Импорт и парсинг',
      num: '1',
      icon: FileDown,
      sub: 'Загрузка DOCX',
    },
    {
      id: 'monitor',
      name: 'Мониторинг задач',
      num: '2',
      icon: Terminal,
      sub: 'Работа пайплайна',
      badge: status !== 'idle' ? 'АКТИВЕН' : undefined,
    },
    {
      id: 'editor',
      name: 'Редактор квизов',
      num: '3',
      icon: SlidersHorizontal,
      sub: 'JSON без кода',
    },
    {
      id: 'deploy',
      name: 'Валидация и загрузка',
      num: '4',
      icon: SendToBack,
      sub: 'В телеграм @QuizBot',
    },
  ];

  return (
    <aside className="w-80 bg-white text-slate-800 flex flex-col justify-between border-r border-slate-200 shrink-0">
      {/* Brand Header */}
      <div className="p-6 border-b border-slate-150">
        <div className="flex items-center gap-3 text-indigo-600">
          <div className="w-10 h-10 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center font-black shadow-sm border border-indigo-150">
            <FlameKindling size={22} className="text-indigo-600 animate-pulse" />
          </div>
          <div>
            <h1 className="font-bold text-lg tracking-tight text-slate-900 leading-none">QuizBot Studio</h1>
            <span className="text-[10px] text-slate-400 font-mono uppercase font-bold tracking-wider">v2.4 Local Manager</span>
          </div>
        </div>
      </div>

      {/* Navigation Menu */}
      <nav className="flex-1 p-4 space-y-1.5 overflow-y-auto">
        <div className="px-3 mb-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Pipeline
        </div>
        
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`w-full group text-left px-3.5 py-2.5 rounded-xl flex items-center gap-3 transition-colors duration-150 ${
                isActive 
                  ? 'bg-indigo-50 text-indigo-700 font-semibold border border-indigo-100/50' 
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50/80'
              }`}
            >
              <div className={`p-1.5 rounded-lg ${isActive ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-500 group-hover:bg-slate-200 group-hover:text-slate-700'} transition-all`}>
                <Icon size={16} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <p className={`text-xs font-semibold truncate ${isActive ? 'text-indigo-900' : 'text-slate-700'}`}>
                    {tab.name}
                  </p>
                  <span className="text-[9px] opacity-40 font-mono">#{tab.num}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className={`text-[10px] truncate ${isActive ? 'text-indigo-500' : 'text-slate-450'}`}>{tab.sub}</span>
                  {tab.badge && (
                    <span className="px-1.5 py-0.5 rounded text-[8px] bg-indigo-100/80 text-indigo-700 font-bold border border-indigo-200/50 animate-pulse">
                      {tab.badge}
                    </span>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </nav>

      {/* Connection & Safe Guards Footer */}
      <div className="p-4 bg-slate-50 border-t border-slate-200 text-xs text-slate-500 space-y-2 select-none">
        <div className="flex items-center justify-between text-[11px] font-semibold">
          <span className="text-slate-400 font-bold">SYSTEM STATUS:</span>
          {status === 'idle' ? (
            <span className="flex items-center gap-1 text-emerald-600 font-bold">
              <span className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)] animate-pulse" /> IDLE
            </span>
          ) : (
            <span className="flex items-center gap-1 text-amber-600 font-bold animate-pulse">
              <span className="w-2 h-2 rounded-full bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.5)]" /> {status.toUpperCase()}
            </span>
          )}
        </div>
        
        {status !== 'idle' && (
          <div className="bg-white border border-slate-200 p-2.5 rounded-lg shadow-sm text-[10px] font-mono text-slate-550 space-y-0.5">
            <span className="text-slate-400 block font-bold">CURRENT STEP:</span>
            <span className="text-slate-800 font-medium truncate block leading-tight">{currentStep}</span>
          </div>
        )}

        <div className="pt-2 border-t border-slate-200/70 flex items-center justify-between text-[9px] font-mono text-slate-400">
          <span>HOST: 127.0.0.1</span>
          <span>DISCORD / TG CONNECT</span>
        </div>
      </div>
    </aside>
  );
}

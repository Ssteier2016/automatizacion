import React, { useState, useEffect, useRef } from 'react';
import { Leaf, Search, Wand2, Mail, MessageCircle, X, ChevronRight, Check } from 'lucide-react';

const App = () => {
  // Estados principales
  const [leads, setLeads] = useState([]);
  const [zona, setZona] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedLeads, setSelectedLeads] = useState(new Set());
  
  // Estados de WhatsApp
  const [waVersion, setWaVersion] = useState('web');
  const [waBody, setWaBody] = useState('Hola {nombre}, ¿cómo estás? Te escribo de Yerba Mate Soberanía para enviarte nuestra lista de precios mayorista.');
  const [waCola, setWaCola] = useState([]);
  const [waCursor, setWaCursor] = useState(0);
  const [isWaModalOpen, setIsWaModalOpen] = useState(false);

  // Estados de Email
  const [emailUser, setEmailUser] = useState('');
  const [emailPass, setEmailPass] = useState('');

  // Estados de Tutorial
  const [tutorialStep, setTutorialStep] = useState(0);
  const [isTutorialOpen, setIsTutorialOpen] = useState(false);
  const [highlightedId, setHighlightedId] = useState(null);

  const tutorialSteps = [
    {
      title: "¡Hola!",
      text: "Configura el sistema en 3 pasos rápidos para empezar a vender.",
      btn: "Empezar",
      highlight: null
    },
    {
      title: "Paso 1: Buscar",
      text: "Escribe una zona y encuentra dietéticas automáticamente.",
      btn: "Siguiente",
      highlight: "step-1"
    },
    {
      title: "Paso 2: Mensaje",
      text: "Configura tu texto. Usaremos el nombre de la tienda solo.",
      btn: "Siguiente",
      highlight: "step-2"
    },
    {
      title: "Paso 3: Enviar",
      text: "Selecciona las tiendas y dale a 'Iniciar Envío' para contactarlas.",
      btn: "Finalizar",
      highlight: "step-3"
    }
  ];

  // Iniciar tutorial al cargar
  useEffect(() => {
    const timer = setTimeout(() => setIsTutorialOpen(true), 500);
    return () => clearTimeout(timer);
  }, []);

  // Función de Búsqueda conectada al backend
  const buscar = async () => {
    if (!zona) return;
    setLoading(true);
    try {
      const res = await fetch('/search_places', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zona, exhaustivo: true })
      });
      const data = await res.json();
      if (data.success) {
        setLeads(data.leads);
        // Autoseleccionar los que tienen teléfono
        const withTel = new Set();
        data.leads.forEach((l, i) => {
          if (l.telefono) withTel.add(i);
        });
        setSelectedLeads(withTel);
      }
    } catch (e) {
      console.error("Error en búsqueda:", e);
    } finally {
      setLoading(false);
    }
  };

  // Manejo de Tutorial
  const nextTutorialStep = () => {
    if (tutorialStep + 1 >= tutorialSteps.length) {
      setIsTutorialOpen(false);
      setHighlightedId(null);
    } else {
      const nextStep = tutorialStep + 1;
      setTutorialStep(nextStep);
      setHighlightedId(tutorialSteps[nextStep].highlight);
    }
  };

  const cerrarTutorial = () => {
    setIsTutorialOpen(false);
    setHighlightedId(null);
  };

  // Lógica WhatsApp
  const toggleSelectAll = () => {
    if (selectedLeads.size === leads.length) {
      setSelectedLeads(new Set());
    } else {
      const all = new Set();
      leads.forEach((l, i) => { if (l.telefono || l.email) all.add(i); });
      setSelectedLeads(all);
    }
  };

  const toggleLead = (index) => {
    const next = new Set(selectedLeads);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setSelectedLeads(next);
  };

  const iniciarWhatsAppMasivo = () => {
    const cola = [];
    selectedLeads.forEach(idx => {
      if (leads[idx] && leads[idx].telefono) cola.push(idx);
    });

    if (cola.length === 0) {
      alert("Selecciona contactos con número de teléfono.");
      return;
    }

    setWaCola(cola);
    setWaCursor(0);
    setIsWaModalOpen(true);
  };

  const abrirSiguienteWA = () => {
    if (waCursor >= waCola.length) return;

    const leadIdx = waCola[waCursor];
    const lead = leads[leadIdx];
    let body = waBody.replace('{nombre}', lead.nombre);
    const encoded = encodeURIComponent(body);
    
    let url = "";
    if (waVersion === 'web') url = `https://web.whatsapp.com/send?phone=${lead.telefono}&text=${encoded}`;
    else url = `whatsapp://send?phone=${lead.telefono}&text=${encoded}`;

    window.open(url, '_blank');
    
    // Actualizar estado visual del lead en la lista
    const newLeads = [...leads];
    newLeads[leadIdx].status = "Enviado";
    setLeads(newLeads);

    setWaCursor(waCursor + 1);
  };

  const getHighlightClass = (id) => {
    return highlightedId === id 
      ? "relative z-[110] ring-4 ring-emerald-500 bg-emerald-900/10 p-4 outline-offset-4 shadow-[0_0_0_9999px_rgba(2,6,23,0.6)]" 
      : "transition-all duration-300";
  };

  return (
    <div className="bg-[#020617] text-slate-200 font-sans min-h-screen overflow-hidden flex flex-col lg:flex-row">
      
      {/* SIDEBAR */}
      <aside className="lg:w-96 bg-[#0b1120] border-r border-slate-800 p-6 space-y-6 flex flex-col overflow-y-auto custom-scroll">
        <div className="flex items-center gap-3">
          <div className="bg-emerald-600 p-2 rounded-xl">
            <Leaf className="text-white" size={24} />
          </div>
          <div>
            <h1 className="text-lg font-black tracking-tighter uppercase leading-none italic">
              Yerba <span className="text-emerald-500">Soberanía</span>
            </h1>
            <p className="text-[9px] text-slate-500 font-bold uppercase tracking-widest">
              Automatización
            </p>
          </div>
        </div>

        {/* BUSCADOR */}
        <div id="step-1" className={getHighlightClass("step-1") + " space-y-4 pt-4 rounded-2xl"}>
          <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-widest border-b border-slate-800 pb-2">1. Localización</h3>
          <div className="flex gap-2">
            <input 
              type="text" 
              value={zona}
              onChange={(e) => setZona(e.target.value)}
              placeholder="Ej: Morón, Buenos Aires" 
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-2xl text-sm outline-none focus:border-emerald-500 transition"
            />
            <button 
              onClick={buscar} 
              disabled={loading}
              className="bg-emerald-600 px-5 rounded-2xl hover:bg-emerald-500 transition disabled:opacity-50"
            >
              {loading ? <div className="animate-spin border-2 border-white/20 border-t-white w-4 h-4 rounded-full" /> : <Search size={18} />}
            </button>
          </div>
        </div>

        {/* WHATSAPP CONFIG */}
        <div id="step-2" className={getHighlightClass("step-2") + " space-y-4 pt-4 rounded-2xl"}>
          <h3 className="text-[10px] font-black text-emerald-500 uppercase tracking-widest border-b border-emerald-900/30 pb-2">2. WhatsApp Uno a Uno</h3>
          <div className="space-y-3">
            <label className="text-[9px] font-bold text-slate-500 uppercase px-1">App de WhatsApp</label>
            <select 
              value={waVersion}
              onChange={(e) => setWaVersion(e.target.value)}
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-xl text-xs outline-none focus:border-emerald-500"
            >
              <option value="web">WhatsApp Web (Navegador)</option>
              <option value="app">WhatsApp Messenger (App)</option>
              <option value="business">WhatsApp Business (App)</option>
            </select>

            <label className="text-[9px] font-bold text-slate-500 uppercase px-1">Mensaje ({'{nombre}'})</label>
            <textarea 
              value={waBody}
              onChange={(e) => setWaBody(e.target.value)}
              rows="3" 
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-xl text-[10px] outline-none focus:border-emerald-500 resize-none"
            />
            
            <button 
              onClick={iniciarWhatsAppMasivo}
              className="w-full bg-emerald-600 text-white font-black py-3 rounded-xl hover:bg-emerald-500 transition flex items-center justify-center gap-2 text-xs uppercase shadow-lg"
            >
              <MessageCircle size={18} /> Iniciar Envío WA
            </button>
          </div>
        </div>

        {/* EMAIL CONFIG */}
        <div className="space-y-4 pt-4">
          <h3 className="text-[10px] font-black text-blue-500 uppercase tracking-widest border-b border-blue-900/30 pb-2">3. Campaña de Email</h3>
          <div className="space-y-3">
            <input 
              type="email" 
              value={emailUser}
              onChange={(e) => setEmailUser(e.target.value)}
              placeholder="Gmail User" 
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-xl text-[10px] outline-none"
            />
            <input 
              type="password" 
              value={emailPass}
              onChange={(e) => setEmailPass(e.target.value)}
              placeholder="App Password" 
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-xl text-[10px] outline-none"
            />
            <button className="w-full bg-blue-600 text-white font-black py-3 rounded-xl hover:bg-blue-500 transition flex items-center justify-center gap-2 text-xs uppercase opacity-50 cursor-not-allowed">
              <Mail size={18} /> Enviar Emails
            </button>
          </div>
        </div>
      </aside>

      {/* CONTENIDO PRINCIPAL */}
      <main className="flex-1 p-8 flex flex-col overflow-hidden">
        <div className="bg-[#0b1120] rounded-[2rem] border border-slate-800 overflow-hidden shadow-2xl flex flex-col flex-1">
          <div className="px-8 py-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/40">
            <div id="step-3" className={getHighlightClass("step-3") + " flex items-center gap-4 rounded-xl p-1"}>
              <input 
                type="checkbox" 
                checked={leads.length > 0 && selectedLeads.size === leads.filter(l => l.telefono || l.email).length}
                onChange={toggleSelectAll}
                className="cursor-pointer"
              />
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">Prospectos Encontrados</h2>
            </div>
            <div className="text-[10px] font-black text-emerald-500 uppercase tracking-widest">
              {leads.length > 0 ? `${leads.length} Resultados` : 'Listo'}
            </div>
          </div>

          <div className="flex-1 overflow-auto custom-scroll">
            <table className="w-full text-[11px] text-left">
              <thead className="bg-slate-900/80 text-[9px] uppercase text-slate-500 font-black sticky top-0">
                <tr>
                  <th className="px-6 py-4 w-10 text-center">Sel</th>
                  <th className="px-6 py-4">Comercio</th>
                  <th className="px-6 py-4">Dirección</th>
                  <th className="px-6 py-4 text-center">WhatsApp</th>
                  <th className="px-6 py-4">Email</th>
                  <th className="px-6 py-4">RRSS</th>
                  <th className="px-6 py-4 text-center">Estado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {leads.length === 0 ? (
                  <tr><td colSpan="7" className="py-20 text-center text-slate-700 italic">Busca una zona para ver resultados...</td></tr>
                ) : (
                  leads.map((lead, i) => (
                    <tr 
                      key={i} 
                      className={`hover:bg-slate-900/40 transition group ${waCola[waCursor] === i ? 'bg-emerald-900/10 border-l-4 border-emerald-500' : ''}`}
                    >
                      <td className="px-6 py-4 text-center">
                        <input 
                          type="checkbox" 
                          disabled={!lead.telefono && !lead.email}
                          checked={selectedLeads.has(i)}
                          onChange={() => toggleLead(i)}
                        />
                      </td>
                      <td className="px-6 py-4 font-bold text-slate-200">{lead.nombre}</td>
                      <td className="px-6 py-4 text-slate-500 max-w-[150px] truncate">{lead.direccion}</td>
                      <td className="px-6 py-4 text-center font-mono text-emerald-500">{lead.telefono || '--'}</td>
                      <td className="px-6 py-4 text-slate-400">{lead.email || <span className="text-slate-800">N/A</span>}</td>
                      <td className="px-6 py-4 flex gap-2">
                        {lead.facebook && <a href={lead.facebook} target="_blank" className="text-blue-400 hover:scale-110 transition"><i className="fab fa-facebook"></i></a>}
                        {lead.instagram && <a href={lead.instagram} target="_blank" className="text-pink-400 hover:scale-110 transition"><i className="fab fa-instagram"></i></a>}
                        {!lead.facebook && !lead.instagram && <span className="text-slate-800">--</span>}
                      </td>
                      <td className="px-6 py-4 text-center">
                        <span className={`text-[9px] font-black uppercase px-2 py-1 rounded ${lead.status === 'Enviado' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-slate-900 text-slate-700'}`}>
                          {lead.status || 'Pendiente'}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      {/* MODAL TUTORIAL MINI */}
      {isTutorialOpen && (
        <div className="fixed inset-0 z-[120] pointer-events-none flex justify-end items-end p-8">
          <div className={`pointer-events-auto bg-slate-900/95 backdrop-blur-xl border border-emerald-500/50 w-full max-w-[280px] p-6 rounded-[1.5rem] shadow-2xl space-y-4 transition-all duration-500 ${isTutorialOpen ? 'translate-y-0 opacity-100' : 'translate-y-10 opacity-0'}`}>
            <div className="flex items-center gap-3 border-b border-slate-800 pb-3">
              <div className="w-10 h-10 bg-emerald-600/20 rounded-full flex items-center justify-center">
                <Wand2 className="text-emerald-500" size={20} />
              </div>
              <h2 className="text-sm font-black text-white uppercase tracking-tighter">Tutorial</h2>
            </div>
            
            <div className="space-y-1">
              <h3 className="text-xs font-bold text-emerald-400">{tutorialSteps[tutorialStep].title}</h3>
              <p className="text-[11px] text-slate-300 leading-relaxed">
                {tutorialSteps[tutorialStep].text}
              </p>
            </div>

            <div className="flex items-center justify-between gap-4 pt-2">
              <button onClick={cerrarTutorial} className="text-slate-500 text-[9px] uppercase font-bold hover:text-white transition">Saltar</button>
              <button onClick={nextTutorialStep} className="bg-emerald-600 text-white font-black px-4 py-2 rounded-lg hover:bg-emerald-500 transition uppercase text-[10px] shadow-lg flex items-center gap-1">
                {tutorialSteps[tutorialStep].btn} <ChevronRight size={12} />
              </button>
            </div>
            
            <div className="flex justify-center gap-1">
              {tutorialSteps.map((_, i) => (
                <div key={i} className={`h-1 w-4 rounded-full transition-all ${i <= tutorialStep ? 'bg-emerald-600' : 'bg-slate-800'}`} />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* MODAL WHATSAPP SECUENCIAL */}
      {isWaModalOpen && (
        <div className="fixed inset-0 z-[200] bg-black/60 backdrop-blur-sm flex items-center justify-center p-6">
          <div className="bg-slate-900 border border-slate-700 w-full max-w-sm p-8 rounded-[2.5rem] shadow-2xl text-center space-y-5 animate-in zoom-in duration-300">
            <div className="w-16 h-16 bg-emerald-600/20 rounded-full flex items-center justify-center mx-auto">
              <MessageCircle className="text-emerald-500" size={32} />
            </div>
            <div>
              <h2 className="text-lg font-black text-white uppercase">
                {waCursor < waCola.length ? leads[waCola[waCursor]].nombre : "¡Completado!"}
              </h2>
              <p className="text-[10px] text-slate-400 mt-1">
                {waCursor < waCola.length ? `Procesando ${waCursor + 1} de ${waCola.length}` : "Has recorrido toda la lista."}
              </p>
            </div>
            
            {waCursor < waCola.length ? (
              <div className="bg-black/40 p-3 rounded-xl border border-slate-800 text-[10px] font-mono text-emerald-500">
                Haz clic para abrir el chat de WhatsApp.
              </div>
            ) : (
              <div className="bg-emerald-500/10 p-3 rounded-xl border border-emerald-500/20 text-[10px] text-emerald-500 flex items-center justify-center gap-2">
                <Check size={14} /> Campaña finalizada con éxito.
              </div>
            )}

            <div className="flex gap-2">
              <button onClick={() => setIsWaModalOpen(false)} className="flex-1 bg-slate-800 text-slate-400 font-bold py-3 rounded-xl text-[10px] uppercase hover:bg-slate-700 transition">
                {waCursor < waCola.length ? "Detener" : "Cerrar"}
              </button>
              {waCursor < waCola.length && (
                <button onClick={abrirSiguienteWA} className="flex-1 bg-emerald-600 text-white font-bold py-3 rounded-xl text-[10px] uppercase hover:bg-emerald-500 transition shadow-lg">
                  Abrir Chat
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;

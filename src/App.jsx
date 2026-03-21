import React, { useState, useEffect } from 'react';
import { Leaf, Search, Wand2, Mail, MessageCircle, ChevronRight, Check, Facebook, Instagram, Phone, Sprout, Tractor, Syringe, Package } from 'lucide-react';

const App = () => {
  // Base de la API apuntando a tu servidor Flask local
  const API_BASE = "http://localhost:5000";

  // Estados principales de la aplicación
  const [leads, setLeads] = useState([]);
  const [zona, setZona] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedLeads, setSelectedLeads] = useState(new Set());
  const [tipoBusqueda, setTipoBusqueda] = useState('todos'); // 'todos' o tipos específicos
  const [filtroTipo, setFiltroTipo] = useState('todos'); // Para filtrar resultados
  
  // Estados para la lógica de WhatsApp
  const [waVersion, setWaVersion] = useState('web');
  const [waBody, setWaBody] = useState('Hola {nombre}, soy [tu nombre] de [tu empresa]. Te contacto porque tenemos insumos y productos agropecuarios de calidad. ¿Te interesaría recibir nuestra lista de precios mayorista?');
  const [waCola, setWaCola] = useState([]);
  const [waCursor, setWaCursor] = useState(0);
  const [isWaModalOpen, setIsWaModalOpen] = useState(false);

  // Estados para la lógica de Email
  const [emailUser, setEmailUser] = useState('');
  const [emailPass, setEmailPass] = useState('');

  // Estados para el Tutorial interactivo
  const [tutorialStep, setTutorialStep] = useState(0);
  const [isTutorialOpen, setIsTutorialOpen] = useState(false);
  const [highlightedId, setHighlightedId] = useState(null);

  const tutorialSteps = [
    { title: "¡Hola!", text: "Configura el sistema en 3 pasos rápidos para contactar negocios agropecuarios.", btn: "Empezar", highlight: null },
    { title: "Paso 1: Buscar", text: "Escribe una zona y encuentra agrocomerciales, agroveterinarias y más.", btn: "Siguiente", highlight: "step-1" },
    { title: "Paso 2: Mensaje", text: "Configura tu texto personalizado para WhatsApp.", btn: "Siguiente", highlight: "step-2" },
    { title: "Paso 3: Enviar", text: "Selecciona los contactos y envía mensajes masivos.", btn: "Finalizar", highlight: "step-3" }
  ];

  // Activa el tutorial automáticamente al cargar la web
  useEffect(() => {
    const timer = setTimeout(() => setIsTutorialOpen(true), 500);
    return () => clearTimeout(timer);
  }, []);

  // Tipos de negocio disponibles
  const tiposNegocio = [
    { id: 'todos', nombre: 'Todos', icon: Sprout, color: 'emerald' },
    { id: 'agrocomercial', nombre: 'Agrocomercial', icon: Package, color: 'blue' },
    { id: 'agroveterinaria', nombre: 'Agroveterinaria', icon: Syringe, color: 'purple' },
    { id: 'agropecuaria', nombre: 'Agropecuaria', icon: Tractor, color: 'green' },
    { id: 'agroinsumos', nombre: 'Agroinsumos', icon: Package, color: 'orange' },
    { id: 'agroanimal', nombre: 'Agroanimal', icon: Sprout, color: 'yellow' }
  ];

  // Función para buscar lugares usando el backend de Flask
  const buscar = async () => {
    if (!zona) return;
    setLoading(true);
    try {
      let url = `${API_BASE}/search_places`;
      let body = { zona, exhaustivo: true };
      
      // Si se selecciona un tipo específico, usar la ruta específica
      if (tipoBusqueda !== 'todos') {
        url = `${API_BASE}/search_agro_by_type`;
        body = { zona, tipo: tipoBusqueda };
      }
      
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (data.success) {
        setLeads(data.leads.map(l => ({ ...l, status: 'Pendiente' })));
        const withContact = new Set();
        data.leads.forEach((l, i) => { 
          if (l.telefono || l.email) withContact.add(i); 
        });
        setSelectedLeads(withContact);
      } else {
        console.error("Error en búsqueda:", data.error);
        alert(data.error || "Error en la búsqueda");
      }
    } catch (e) {
      console.error("Error en la conexión con el servidor:", e);
      alert("Error de conexión con el servidor");
    } finally {
      setLoading(false);
    }
  };

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

  const toggleSelectAll = () => {
    const contactables = leads.filter(l => l.telefono || l.email).length;
    if (selectedLeads.size === contactables && contactables > 0) {
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

  // Filtrar leads por tipo si se selecciona filtro
  const leadsFiltrados = filtroTipo === 'todos' 
    ? leads 
    : leads.filter(lead => lead.tipo === filtroTipo);

  // Generación de URL de WhatsApp dinámica
  const generarUrlWA = (telefono, nombre) => {
    const body = waBody.replace('{nombre}', nombre);
    const encoded = encodeURIComponent(body);
    if (waVersion === 'web') {
        return `https://web.whatsapp.com/send?phone=${telefono}&text=${encoded}`;
    }
    return `whatsapp://send?phone=${telefono}&text=${encoded}`;
  };

  // Abrir chat individual usando siempre la misma ventana
  const abrirChatIndividual = (telefono, nombre, index) => {
    if (!telefono) return;
    const url = generarUrlWA(telefono, nombre);
    window.open(url, "whatsapp_session");
    
    const newLeads = [...leads];
    newLeads[index].status = "WA Abierto";
    setLeads(newLeads);
  };

  const iniciarWhatsAppMasivo = () => {
    const cola = [];
    selectedLeads.forEach(idx => { if (leads[idx]?.telefono) cola.push(idx); });
    if (cola.length === 0) return alert("Selecciona contactos con número de teléfono.");
    
    setWaCola(cola);
    setWaCursor(0);
    setIsWaModalOpen(true);
  };

  const abrirSiguienteWA = () => {
    if (waCursor >= waCola.length) return;
    const leadIdx = waCola[waCursor];
    const lead = leads[leadIdx];
    
    const url = generarUrlWA(lead.telefono, lead.nombre);
    window.open(url, "whatsapp_session");
    
    const newLeads = [...leads];
    newLeads[leadIdx].status = "WA Abierto";
    setLeads(newLeads);
    setWaCursor(waCursor + 1);
  };

  const iniciarEmailMasivo = async () => {
    const selected = [];
    selectedLeads.forEach(idx => { 
      if (leads[idx]?.email) selected.push({ ...leads[idx], original_index: idx }); 
    });
    
    if (selected.length === 0) return alert("No hay emails válidos seleccionados.");
    if (!emailUser || !emailPass) return alert("Completa tus credenciales de Gmail.");

    try {
      await fetch(`${API_BASE}/start_email_campaign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leads: selected,
          email_user: emailUser,
          email_pass: emailPass,
          subject: "Productos Agropecuarios - Lista de Precios",
          body: "Hola {nombre},\n\nSomos proveedores de insumos y productos agropecuarios. Adjuntamos nuestra lista de precios mayorista para que la revises.\n\nQuedamos a tu disposición.\n\nSaludos cordiales.",
          attach_image: false
        })
      });
      alert(`Iniciado envío de ${selected.length} correos.`);
    } catch (e) {
      alert("Error al conectar con el servidor.");
    }
  };

  // Obtener icono según tipo de negocio
  const getTipoIcon = (tipo) => {
    switch(tipo) {
      case 'Agroveterinaria': return <Syringe size={12} className="text-purple-400" />;
      case 'Agrocomercial': return <Package size={12} className="text-blue-400" />;
      case 'Agropecuaria': return <Tractor size={12} className="text-green-400" />;
      case 'Agroinsumos': return <Package size={12} className="text-orange-400" />;
      case 'Agroanimal': return <Sprout size={12} className="text-yellow-400" />;
      default: return <Sprout size={12} className="text-emerald-400" />;
    }
  };

  const getHighlightClass = (id) => {
    return highlightedId === id 
      ? "relative z-[110] ring-4 ring-emerald-500 bg-emerald-900/10 p-4 rounded-2xl shadow-[0_0_0_9999px_rgba(2,6,23,0.6)]" 
      : "transition-all duration-300";
  };

  // Estadísticas de tipos encontrados
  const tiposEncontrados = leads.reduce((acc, lead) => {
    const tipo = lead.tipo || 'Agropecuario';
    acc[tipo] = (acc[tipo] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="bg-[#020617] text-slate-200 font-sans min-h-screen flex flex-col lg:flex-row overflow-hidden">
      
      {/* SIDEBAR - Deslizable independientemente */}
      <aside className="lg:w-96 bg-[#0b1120] border-r border-slate-800 p-6 space-y-6 flex flex-col shrink-0 overflow-y-auto h-screen custom-scroll">
        <div className="flex items-center gap-3">
          <div className="bg-emerald-600 p-2 rounded-xl"><Leaf className="text-white" size={24} /></div>
          <div>
            <h1 className="text-lg font-black tracking-tighter uppercase leading-none italic">Agro <span className="text-emerald-500">Soberanía</span></h1>
            <p className="text-[8px] text-slate-500 mt-1">Proveedores Agropecuarios</p>
          </div>
        </div>

        {/* PASO 1: BUSCADOR AGROPECUARIO */}
        <div id="step-1" className={getHighlightClass("step-1") + " space-y-4 pt-4"}>
          <h3 className="text-[10px] font-black text-slate-500 uppercase tracking-widest border-b border-slate-800 pb-2">1. Buscar Establecimientos</h3>
          
          {/* Selector de tipo de búsqueda */}
          <div className="grid grid-cols-2 gap-2">
            {tiposNegocio.map(tipo => {
              const Icon = tipo.icon;
              return (
                <button
                  key={tipo.id}
                  onClick={() => setTipoBusqueda(tipo.id)}
                  className={`p-2 rounded-xl text-[9px] font-bold uppercase transition flex items-center justify-center gap-1 ${
                    tipoBusqueda === tipo.id 
                      ? `bg-${tipo.color}-600 text-white` 
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                  }`}
                >
                  <Icon size={12} />
                  {tipo.nombre}
                </button>
              );
            })}
          </div>
          
          <div className="flex gap-2">
            <input 
              type="text" 
              value={zona} 
              onChange={(e) => setZona(e.target.value)} 
              placeholder="Ej: Marcos Juárez, Córdoba" 
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-2xl text-sm outline-none focus:border-emerald-500 transition" 
              onKeyPress={(e) => e.key === 'Enter' && buscar()}
            />
            <button 
              onClick={buscar} 
              disabled={loading} 
              className="bg-emerald-600 px-5 rounded-2xl hover:bg-emerald-500 transition disabled:opacity-50"
            >
              {loading ? <div className="animate-spin border-2 border-white/20 border-t-white w-4 h-4 rounded-full" /> : <Search size={18} />}
            </button>
          </div>
          
          {/* Mostrar estadísticas si hay resultados */}
          {leads.length > 0 && Object.keys(tiposEncontrados).length > 0 && (
            <div className="bg-slate-900/50 rounded-xl p-2">
              <p className="text-[8px] text-slate-400 uppercase mb-1">Tipos encontrados:</p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(tiposEncontrados).map(([tipo, count]) => (
                  <span key={tipo} className="text-[8px] bg-slate-800 px-2 py-0.5 rounded-full">
                    {tipo}: {count}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* PASO 2: WHATSAPP */}
        <div id="step-2" className={getHighlightClass("step-2") + " space-y-4 pt-4"}>
          <h3 className="text-[10px] font-black text-emerald-500 uppercase tracking-widest border-b border-emerald-900/30 pb-2">2. WhatsApp - Ventas Agro</h3>
          <div className="space-y-3">
            <select 
              value={waVersion} 
              onChange={(e) => setWaVersion(e.target.value)} 
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-xl text-xs outline-none focus:border-emerald-500"
            >
              <option value="web">WhatsApp Web (Navegador)</option>
              <option value="app">WhatsApp Messenger (App)</option>
            </select>
            <textarea 
              value={waBody} 
              onChange={(e) => setWaBody(e.target.value)} 
              rows="4" 
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-xl text-[10px] outline-none focus:border-emerald-500 resize-none" 
              placeholder="Mensaje personalizado para negocios agropecuarios..."
            />
            <button 
              onClick={iniciarWhatsAppMasivo} 
              className="w-full bg-emerald-600 text-white font-black py-3 rounded-xl hover:bg-emerald-500 transition flex items-center justify-center gap-2 text-xs uppercase shadow-lg"
            >
              <MessageCircle size={18} /> Iniciar Envío WA
            </button>
          </div>
        </div>

        {/* PASO 3: EMAIL */}
        <div className="space-y-4 pt-4 pb-10">
          <h3 className="text-[10px] font-black text-blue-500 uppercase tracking-widest border-b border-blue-900/30 pb-2">3. Email Campaña</h3>
          <div className="space-y-3">
            <input 
              type="email" 
              value={emailUser} 
              onChange={(e) => setEmailUser(e.target.value)} 
              placeholder="Gmail User" 
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-xl text-[10px] outline-none focus:border-blue-500" 
            />
            <input 
              type="password" 
              value={emailPass} 
              onChange={(e) => setEmailPass(e.target.value)} 
              placeholder="App Password" 
              className="w-full bg-slate-900 border border-slate-800 p-3 rounded-xl text-[10px] outline-none focus:border-blue-500" 
            />
            <button 
              onClick={iniciarEmailMasivo} 
              className="w-full bg-blue-600 text-white font-black py-3 rounded-xl hover:bg-blue-500 transition flex items-center justify-center gap-2 text-xs uppercase shadow-lg"
            >
              <Mail size={18} /> Enviar Emails
            </button>
          </div>
        </div>
      </aside>

      {/* CONTENIDO PRINCIPAL - Deslizable independientemente */}
      <main className="flex-1 p-4 lg:p-8 flex flex-col h-screen overflow-y-auto custom-scroll">
        <div className="bg-[#0b1120] rounded-[2rem] border border-slate-800 shadow-2xl flex flex-col flex-1 min-h-fit">
          <div className="px-8 py-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/40 sticky top-0 z-10 rounded-t-[2rem] flex-wrap gap-3">
            <div id="step-3" className={getHighlightClass("step-3") + " flex items-center gap-4 rounded-xl p-1"}>
              <input 
                type="checkbox" 
                checked={leads.length > 0 && selectedLeads.size === leads.filter(l => l.telefono || l.email).length} 
                onChange={toggleSelectAll} 
                className="cursor-pointer" 
              />
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">Prospectos Agro</h2>
            </div>
            
            {/* Filtro por tipo en resultados */}
            {leads.length > 0 && (
              <div className="flex gap-1">
                <button
                  onClick={() => setFiltroTipo('todos')}
                  className={`px-2 py-1 rounded text-[9px] uppercase font-bold transition ${
                    filtroTipo === 'todos' ? 'bg-emerald-600' : 'bg-slate-800 hover:bg-slate-700'
                  }`}
                >
                  Todos ({leads.length})
                </button>
                {Object.entries(tiposEncontrados).map(([tipo, count]) => (
                  <button
                    key={tipo}
                    onClick={() => setFiltroTipo(tipo)}
                    className={`px-2 py-1 rounded text-[9px] uppercase font-bold transition ${
                      filtroTipo === tipo ? 'bg-emerald-600' : 'bg-slate-800 hover:bg-slate-700'
                    }`}
                  >
                    {tipo} ({count})
                  </button>
                ))}
              </div>
            )}
            
            <div className="text-[10px] font-black text-emerald-500 uppercase">
              {leads.length > 0 ? `${leadsFiltrados.length} Resultados` : 'Listo'}
            </div>
          </div>
          
          <div className="flex-1 overflow-x-auto overflow-y-visible">
            <table className="w-full text-[11px] text-left min-w-[900px]">
              <thead className="bg-slate-900/80 text-[9px] uppercase text-slate-500 font-black sticky top-0">
                <tr>
                  <th className="px-6 py-4 w-10 text-center">Sel</th>
                  <th className="px-6 py-4">Comercio</th>
                  <th className="px-6 py-4">Tipo</th>
                  <th className="px-6 py-4">Dirección</th>
                  <th className="px-6 py-4 text-center">WhatsApp</th>
                  <th className="px-6 py-4">Email</th>
                  <th className="px-6 py-4">RRSS</th>
                  <th className="px-6 py-4 text-center">Estado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {leadsFiltrados.length === 0 ? (
                  <tr><td colSpan="8" className="py-20 text-center text-slate-700 italic">Busca una zona para ver resultados...</td></tr>
                ) : (
                  leadsFiltrados.map((lead, idx) => {
                    const originalIndex = leads.findIndex(l => l.nombre === lead.nombre && l.direccion === lead.direccion);
                    return (
                      <tr 
                        key={originalIndex} 
                        className={`hover:bg-slate-900/40 transition group ${waCola[waCursor] === originalIndex ? 'bg-emerald-900/10 border-l-4 border-emerald-500' : ''}`}
                      >
                        <td className="px-6 py-4 text-center">
                          <input 
                            type="checkbox" 
                            disabled={!lead.telefono && !lead.email} 
                            checked={selectedLeads.has(originalIndex)} 
                            onChange={() => toggleLead(originalIndex)} 
                          />
                        </td>
                        <td className="px-6 py-4 font-bold text-slate-200">{lead.nombre}</td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-1">
                            {getTipoIcon(lead.tipo)}
                            <span className="text-[9px] text-slate-400">{lead.tipo || 'Agropecuario'}</span>
                          </div>
                        </td>
                        <td className="px-6 py-4 text-slate-500 max-w-[150px] truncate">{lead.direccion}</td>
                        <td className="px-6 py-4 text-center">
                          {lead.telefono ? (
                            <button 
                              onClick={() => abrirChatIndividual(lead.telefono, lead.nombre, originalIndex)}
                              className="text-emerald-500 font-mono hover:underline flex items-center justify-center gap-1 w-full"
                            >
                              <Phone size={12} /> {lead.telefono}
                            </button>
                          ) : '--'}
                        </td>
                        <td className="px-6 py-4 text-slate-400">{lead.email || <span className="text-slate-800">N/A</span>}</td>
                        <td className="px-6 py-4 flex gap-3">
                          {lead.facebook && <a href={lead.facebook} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:scale-125 transition"><Facebook size={14}/></a>}
                          {lead.instagram && <a href={lead.instagram} target="_blank" rel="noopener noreferrer" className="text-pink-400 hover:scale-125 transition"><Instagram size={14}/></a>}
                        </td>
                        <td className="px-6 py-4 text-center">
                          <span className={`text-[9px] font-black uppercase px-2 py-1 rounded ${lead.status === 'WA Abierto' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-slate-900 text-slate-700'}`}>
                            {lead.status}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      {/* MODAL TUTORIAL MINIATURA */}
      {isTutorialOpen && (
        <div className="fixed inset-0 z-[120] pointer-events-none flex justify-end items-end p-8">
          <div className="pointer-events-auto bg-slate-900/95 backdrop-blur-xl border border-emerald-500/50 w-full max-w-[280px] p-6 rounded-[1.5rem] shadow-2xl space-y-4">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-3">
              <div className="w-10 h-10 bg-emerald-600/20 rounded-full flex items-center justify-center">
                <Wand2 className="text-emerald-500" size={20} />
              </div>
              <h2 className="text-sm font-black text-white uppercase tracking-tighter">Tutorial Agro</h2>
            </div>
            <div className="space-y-1">
              <h3 className="text-xs font-bold text-emerald-400">{tutorialSteps[tutorialStep].title}</h3>
              <p className="text-[11px] text-slate-300 leading-relaxed">{tutorialSteps[tutorialStep].text}</p>
            </div>
            <div className="flex items-center justify-between gap-4 pt-2">
              <button onClick={cerrarTutorial} className="text-slate-500 text-[9px] uppercase font-bold hover:text-white transition">Saltar</button>
              <button onClick={nextTutorialStep} className="bg-emerald-600 text-white font-black px-4 py-2 rounded-lg hover:bg-emerald-500 transition uppercase text-[10px] shadow-lg flex items-center gap-1">
                {tutorialSteps[tutorialStep].btn} <ChevronRight size={12} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL WHATSAPP SECUENCIAL */}
      {isWaModalOpen && (
        <div className="fixed inset-0 z-[200] bg-black/60 backdrop-blur-sm flex items-center justify-center p-6">
          <div className="bg-slate-900 border border-slate-700 w-full max-w-sm p-8 rounded-[2.5rem] shadow-2xl text-center space-y-5">
            <div className="w-16 h-16 bg-emerald-600/20 rounded-full flex items-center justify-center mx-auto">
              <MessageCircle className="text-emerald-500" size={32} />
            </div>
            <div>
              <h2 className="text-lg font-black text-white uppercase">
                {waCursor < waCola.length ? leads[waCola[waCursor]]?.nombre : "¡Completado!"}
              </h2>
              <p className="text-[10px] text-slate-400 mt-1">
                {waCursor < waCola.length ? `Procesando ${waCursor + 1} de ${waCola.length}` : "Campaña finalizada."}
              </p>
            </div>
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

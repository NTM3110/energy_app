
        (function () {
            window.showFaultInfo = async function(start, end) {
                const modalContent = document.getElementById('fault-modal-content');
                const titleEl = document.getElementById('fault-info-title');
                const summaryId = document.getElementById('modal-summary-id');
                const summaryRange = document.getElementById('modal-summary-range');
                const summaryScenario = document.getElementById('modal-summary-scenario');
                const closeBtn = document.getElementById('close-fault-modal');

                if (!modalContent) return;

                // Set title and summary placeholders
                if (titleEl) titleEl.textContent = `Meter Status - ${new Date(start).toLocaleString()}`;
                if (summaryRange) summaryRange.textContent = `${new Date(start).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})} - ${new Date(end).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}`;
                
                modalContent.innerHTML = '<div style="text-align:center; padding:40px;"><div class="loader-ring" style="border-top-color:var(--primary-color); width:30px; height:30px;"></div><p style="margin-top:10px; color:var(--text-secondary);">Fetching faulty meter data...</p></div>';
                
                // Close button handler 
                if (closeBtn) {
                    closeBtn.onclick = () => {
                        if (window.$ && $.fn.modal) {
                            $('#fault-info-modal').modal('hide');
                        } else {
                            const modal = document.getElementById('fault-info-modal');
                            if (modal) {
                                modal.style.display = 'none';
                                modal.classList.remove('in', 'show');
                            }
                        }
                    };
                }

                // Show modal (using jQuery/Bootstrap)
                if (window.$ && $.fn.modal) {
                    $('#fault-info-modal').modal('show');
                } else {
                    const modal = document.getElementById('fault-info-modal');
                    if (modal) {
                        modal.style.display = 'block';
                        modal.classList.add('in', 'show');
                        modal.style.opacity = '1';
                    }
                }

                try {
                    const res = await fetch(`${CONFIG.baseUrl}/faults/by-window?window_start_ts=${encodeURIComponent(start)}&window_end_ts=${encodeURIComponent(end)}`);
                    if (!res.ok) {
                        if (res.status === 404) {
                            modalContent.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-secondary);"><i class="fa fa-info-circle" style="font-size:30px; margin-bottom:10px;"></i><p>No fault record found for this specific window.</p></div>';
                        } else {
                            throw new Error('Failed to fetch fault data');
                        }
                        return;
                    }
                    
                    const data = await res.json();
                    
                    // Update summary info
                    if (summaryId) summaryId.textContent = data.id || 'N/A';
                    if (summaryScenario) {
                        summaryScenario.textContent = data.scenario_code || 'N/A';
                        summaryScenario.className = `scenario-pill ${data.scenario_code === 'ALL_OK' ? 'normal' : 'warning'}`;
                    }
                    
                    if (!data.faults || data.faults.length === 0) {
                        modalContent.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-secondary);"><i class="fa fa-check-circle" style="font-size:30px; margin-bottom:10px; color:var(--success-color);"></i><p>No faulty meters recorded for this period.</p></div>';
                        return;
                    }

                    modalContent.innerHTML = `
                        <div class="table-responsive" style="max-height: 400px;">
                            <table class="table" style="margin-bottom:0;">
                                <thead style="background: #fdfdfd;">
                                    <tr>
                                        <th style="border-top:none; color:#64748b; font-size:11px; text-align: center;">METER SERIAL</th>
                                        <th style="border-top:none; color:#64748b; font-size:11px; text-align: center;">METER NAME</th>
                                        <th style="border-top:none; color:#64748b; font-size:11px; text-align: center;">FAULT START</th>
                                        <th style="border-top:none; color:#64748b; font-size:11px; text-align: center;">FAULT END</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${data.faults.map(f => `
                                        <tr>
                                            <td style="font-weight:400; padding:12px 16px; color:#64748b; text-align: center;">${f.meter_serial}</td>
                                            <td style="padding:12px 16px; font-weight:700; color:#001f8f; text-align: center;">${f.meter_name || 'N/A'}</td>
                                            <td style="padding:12px 16px; text-align: center;">${new Date(f.fault_start_ts).toLocaleString([], {year:'2-digit', month:'numeric', day:'numeric', hour:'numeric', minute:'2-digit'})}</td>
                                            <td style="padding:12px 16px; color:#64748b; text-align: center;">${f.fault_end_ts ? new Date(f.fault_end_ts).toLocaleString([], {year:'2-digit', month:'numeric', day:'numeric', hour:'numeric', minute:'2-digit'}) : '--'}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    `;
                } catch (e) {
                    console.error('Fault Modal Error:', e);
                    modalContent.innerHTML = `<div style="text-align:center; padding:40px; color:var(--danger-color);"><i class="fa fa-exclamation-triangle" style="font-size:30px; margin-bottom:10px;"></i><p>Error loading fault info: ${e.message}</p></div>`;
                }
            }
            // Configuration & State
            const CONFIG = {
                baseUrl: 'http://192.168.4.117:8001/api',
                pollingInterval: 30000 
            };

            const STATE = {
                meters: [],
                isPolling: false,
                currentEnergyPage: 'analysis',
                lastUpdateData: null,
                historyData: [],
                selectedMeterFilter: null,
                roles: [],
                sources: []
            };

            // DOM Elements
            const elements = {
                meterTableBody: document.getElementById('meter-list-body'),
                meterManagementBody: document.getElementById('meter-management-body'),
                activityContainer: document.getElementById('activity-cards'),
                statTotal: document.getElementById('stat-total-meters'),
                statConnected: document.getElementById('stat-connected-meters'),
                statDisconnected: document.getElementById('stat-disconnected-meters'),
                statReading: document.getElementById('stat-reading-meters'),
                pollingBadgeText: document.getElementById('polling-badge-text'),
                pollingLoader: document.getElementById('polling-loader'),
                pollingStatusText: document.getElementById('polling-status-text')
            };

            // --- API Service ---
            async function fetchAllMeters() {
                try {
                    // Try to load from cache first for immediate UI
                    const cached = localStorage.getItem('tariff_meters_cache');
                    if (cached) {
                        STATE.meters = JSON.parse(cached);
                        renderMeterList();
                        renderMeterManagement();
                        updateStats();
                    }

                    const response = await fetch(`${CONFIG.baseUrl}/get_all_meters_info`);
                    if (!response.ok) throw new Error('Failed to fetch meters');
                    const freshMeters = await response.json();
                    
                    // Merge fresh info with existing connected states if any
                    freshMeters.forEach(m => {
                        const existing = STATE.meters.find(em => em.meter_id == m.meter_id);
                        if (existing) {
                            m._isConnected = existing._isConnected;
                            m._statusText = existing._statusText;
                        }
                    });

                    STATE.meters = freshMeters;
                    localStorage.setItem('tariff_meters_cache', JSON.stringify(STATE.meters));
                    
                    renderMeterList();
                    renderMeterManagement();
                    updateStats();
                } catch (error) {
                    console.error('API Error (Meters):', error);
                }
            }

            async function pollStatus() {
                if (STATE.isPolling) return;
                STATE.isPolling = true;
                
                if (elements.pollingLoader) elements.pollingLoader.style.display = 'inline-block';
                if (elements.pollingBadgeText) elements.pollingBadgeText.textContent = 'POLLING...';

                try {
                    const response = await fetch(`${CONFIG.baseUrl}/meter_loop_status`);
                    if (!response.ok) throw new Error('Failed to fetch status');
                    const statusData = await response.json();
                    
                    updateStatusUI(statusData);
                } catch (error) {
                    console.error('API Error (Status):', error);
                } finally {
                    STATE.isPolling = false;
                    setTimeout(() => {
                        if (elements.pollingLoader) elements.pollingLoader.style.display = 'none';
                        if (elements.pollingBadgeText) elements.pollingBadgeText.textContent = 'SYNCED';
                    }, 1000);
                }
            }

            // --- UI Rendering ---
            function renderMeterList() {
                if (!elements.meterTableBody) return;
                elements.meterTableBody.innerHTML = STATE.meters.map(meter => {
                    const isConnected = meter._isConnected;
                    const rawStatus = (meter._statusText || '').toLowerCase();
                    const isFailed = rawStatus.includes('failed') || rawStatus === 'disconnected' || rawStatus === 'idle';
                    
                    const statusText = isConnected ? 'Connected' : (rawStatus.includes('failed') ? 'Failed' : meter._statusText || 'Disconnected');
                    const typeLabel = (meter.type || 'N/A').toUpperCase().includes('DMI') ? 'EDMI' : (meter.type || '--');
                    const safeName = (meter.meter_name || 'N/A').replace(/'/g, "\\'").replace(/"/g, '&quot;');

                    return `
                        <tr class="meter-row">
                            <td>${meter.serial_number}</td>
                            <td class="tm-link">
                                <a href="javascript:void(0)" onclick="openMeterDetail(${meter.meter_id}, '${safeName}')" style="color:var(--primary-color); font-weight:600; text-decoration:none;">
                                    ${meter.meter_name || 'N/A'}
                                </a>
                            </td>
                            <td>${meter.outstation || '--'}</td>
                            <td>${typeLabel}</td>
                            <td>${meter.model || '--'}</td>
                            <td id="status-cell-${meter.meter_id}">
                                <span class="status-pill ${isConnected ? 'connected' : (isFailed ? 'failed' : '')}">${statusText}</span>
                            </td>
                        </tr>
                    `;
                }).join('') || '<tr><td colspan="6" style="text-align:center;">No meters found.</td></tr>';
            }

            function renderMeterManagement() {
                if (!elements.meterManagementBody) return;
                elements.meterManagementBody.innerHTML = STATE.meters.map(meter => {
                    const isConnected = meter._isConnected;
                    const rawStatus = (meter._statusText || '').toLowerCase();
                    const isFailed = rawStatus.includes('failed') || rawStatus.includes('timeout') || rawStatus === 'disconnected' || rawStatus === 'idle';
                    
                    const statusText = isConnected ? 'Connected' : (isFailed ? 'Failed' : meter._statusText || 'Disconnected');
                    const safeMeter = encodeURIComponent(JSON.stringify(meter));

                    return `
                        <tr>
                            <td>${meter.meter_id}</td>
                            <td>${meter.serial_number}</td>
                            <td>${meter.username}</td>
                            <td>********</td>
                            <td id="mgt-status-${meter.meter_id}">
                                <span class="status-pill ${isConnected ? 'connected' : (isFailed ? 'failed' : '')}">${statusText}</span>
                            </td>
                            <td style="text-align: center;">
                                <button class="btn-action" onclick="editMeter(this.dataset.meter)" data-meter="${safeMeter}"><i class="fa fa-pencil"></i></button>
                                <button class="btn-action delete" onclick="deleteMeter(${meter.meter_id}, ${meter.serial_number})"><i class="fa fa-trash"></i></button>
                            </td>
                        </tr>
                    `;
                }).join('');
            }

            // --- Form Handlers ---
            window.showMeterForm = function() {
                document.getElementById('meter-form-card').style.display = 'block';
                document.getElementById('meter-list-wrapper').style.display = 'none';
                document.getElementById('meter-form-title').textContent = 'Add New Meter';
                document.getElementById('meter-form').reset();
                document.getElementById('meter_id').value = '';
                document.getElementById('serial_number').readOnly = false;
                
                // Set default owner_id inside form if not present
                document.getElementById('source_id').disabled = true;
                document.getElementById('source_id').value = '';
            };

            window.hideMeterForm = function() {
                document.getElementById('meter-form-card').style.display = 'none';
                document.getElementById('meter-list-wrapper').style.display = 'block';
                document.getElementById('meter-form').reset();
            };

            window.handleRoleChange = function() {
                const roleSelect = document.getElementById('role_id');
                const sourceSelect = document.getElementById('source_id');
                const roleName = roleSelect.options[roleSelect.selectedIndex]?.text;
                if (roleName === 'SOURCE') {
                    sourceSelect.disabled = false;
                } else {
                    sourceSelect.disabled = true;
                    sourceSelect.value = '';
                }
            };

            window.editMeter = function(encodedMeter) {
                const meter = JSON.parse(decodeURIComponent(encodedMeter));
                showMeterForm();
                document.getElementById('meter-form-title').textContent = 'Edit Meter';
                
                document.getElementById('meter_id').value = meter.meter_id;
                document.getElementById('serial_number').value = meter.serial_number;
                document.getElementById('serial_number').readOnly = true;
                
                document.getElementById('meter_name').value = meter.meter_name || '';
                document.getElementById('outstation').value = meter.outstation || '';
                document.getElementById('username').value = meter.username || '';
                document.getElementById('password').value = meter.password || '';
                document.getElementById('type').value = meter.type || '';
                document.getElementById('model').value = meter.model || '';
                
                document.getElementById('role_id').value = meter.role || '';
                handleRoleChange(); // unlock source_id if needed
                document.getElementById('source_id').value = meter.source_id || '';
                
                if (meter.survey_type && meter.survey_type.length > 0) {
                    document.getElementById('survey_type').value = meter.survey_type.join(', ');
                } else {
                    document.getElementById('survey_type').value = '';
                }
            };

            window.deleteMeter = async function(id, serialNumber) {
                if (!confirm('Are you sure you want to delete meter ' + serialNumber + '?')) return;
                try {
                    const res = await fetch(\`\${CONFIG.baseUrl}/delete_meter/\${id}\`, { method: 'DELETE' });
                    if (!res.ok) throw new Error('Failed to delete');
                    await fetchAllMeters(); // Refresh table
                } catch (e) {
                    console.error(e);
                    alert('Error deleting meter.');
                }
            };

            window.handleMeterSubmit = async function(e) {
                e.preventDefault();
                
                const isEditing = !!document.getElementById('meter_id').value;
                const endpoint = isEditing ? '/update_meter' : '/add_meter';
                const method = isEditing ? 'PUT' : 'POST';
                
                const surveyStr = document.getElementById('survey_type').value || '';
                const surveyArr = surveyStr.split(',').map(s => s.trim()).filter(s => s);

                const payload = {
                    serial_number: parseInt(document.getElementById('serial_number').value, 10),
                    meter_name: document.getElementById('meter_name').value || undefined,
                    outstation: document.getElementById('outstation').value ? parseInt(document.getElementById('outstation').value, 10) : undefined,
                    username: document.getElementById('username').value,
                    password: document.getElementById('password').value,
                    type: document.getElementById('type').value,
                    model: document.getElementById('model').value,
                    survey_type: surveyArr.length > 0 ? surveyArr : undefined,
                    owner_id: 1, // Default matching angular code
                    role: document.getElementById('role_id').value ? parseInt(document.getElementById('role_id').value, 10) : undefined,
                    source_id: document.getElementById('source_id').value && !document.getElementById('source_id').disabled ? parseInt(document.getElementById('source_id').value, 10) : undefined
                };

                try {
                    const res = await fetch(CONFIG.baseUrl + endpoint, {
                        method: method,
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    
                    if (!res.ok) throw new Error('Failed to save');
                    hideMeterForm();
                    await fetchAllMeters();
                } catch (err) {
                    console.error(err);
                    alert('Error saving meter configuration.');
                }
            };

            async function fetchRolesAndSources() {
                try {
                    const rRes = await fetch(\`\${CONFIG.baseUrl}/energy/roles\`);
                    if (rRes.ok) {
                        const rData = await rRes.json();
                        STATE.roles = rData.items || [];
                        const roleSelect = document.getElementById('role_id');
                        roleSelect.innerHTML = '<option value="">None</option>' + STATE.roles.map(r => \`<option value="\${r.id}">\${r.name}</option>\`).join('');
                    }

                    const sRes = await fetch(\`\${CONFIG.baseUrl}/energy/sources\`);
                    if (sRes.ok) {
                        const sData = await sRes.json();
                        STATE.sources = sData.items || [];
                        const sourceSelect = document.getElementById('source_id');
                        sourceSelect.innerHTML = '<option value="">None</option>' + STATE.sources.map(s => \`<option value="\${s.id}">\${s.name} (ID: \${s.id})</option>\`).join('');
                    }
                } catch(e) {
                    console.error('Error fetching roles/sources', e);
                }
            };


            window.openMeterDetail = function(meterId, meterName) {
                const dashboardView = document.getElementById('tariff-dashboard-view');
                const detailView = document.getElementById('tariff-meter-detail');
                const detailTitle = document.getElementById('detail-meter-name');
                const detailIframe = document.getElementById('detail-iframe');

                if (dashboardView && detailView) {
                    dashboardView.style.display = 'none';
                    detailView.style.display = 'block';
                    if (detailTitle) detailTitle.textContent = meterName;
                    
                    // Point to the profile reading page
                    if (detailIframe) {
                        detailIframe.src = `GraphMeasurements.cshtml?DeviceID=${meterId}`;
                    }
                }
            };
            
            document.getElementById('back-to-meter-list').addEventListener('click', () => {
                document.getElementById('tariff-dashboard-view').style.display = 'block';
                document.getElementById('tariff-meter-detail').style.display = 'none';
                document.getElementById('detail-iframe').src = 'about:blank';
            });

            function updateStatusUI(data) {
                if (!data.meter_status) return;

                const now = new Date();
                elements.pollingStatusText.textContent = `Last update: ${now.toLocaleTimeString()}`;

                let connectedCount = 0;
                let readingCount = 0;
                
                // Track current connected states in STATE.meters for sorting
                data.meter_status.forEach(status => {
                    const rawStatus = (status.status || '').toLowerCase();
                    const isConnected = rawStatus === 'read_ok' || rawStatus === 'prelogin_ok' || rawStatus === 'connected' || rawStatus === 'functional' || rawStatus === 'reading';
                    const isFailed = rawStatus.includes('failed') || rawStatus.includes('timeout') || rawStatus === 'disconnected' || rawStatus === 'idle';
                    
                    const meter = STATE.meters.find(m => m.meter_id == status.meter_id);
                    if (meter) {
                        meter._isConnected = isConnected;
                        meter._statusText = isConnected ? 'Connected' : (isFailed ? 'Failed' : status.status);
                    }
                    if (isConnected) connectedCount++;
                    if (rawStatus === 'reading') readingCount++;
                });

                // Persist state
                localStorage.setItem('tariff_meters_cache', JSON.stringify(STATE.meters));
                localStorage.setItem('tariff_last_status', JSON.stringify(data));

                // Sort STATE.meters so connected shows first
                STATE.meters.sort((a, b) => (b._isConnected ? 1 : 0) - (a._isConnected ? 1 : 0));
                
                // Update Overview Numbers
                if (elements.statTotal) elements.statTotal.textContent = STATE.meters.length;
                if (elements.statConnected) elements.statConnected.textContent = connectedCount;
                if (elements.statDisconnected) elements.statDisconnected.textContent = STATE.meters.length - connectedCount;
                if (elements.statReading) elements.statReading.textContent = readingCount;
                
                // Re-render lists with new order
                renderMeterList();
                renderMeterManagement();

                // Build activity cards
                if (elements.activityContainer) {
                    elements.activityContainer.innerHTML = '';
                    
                    // Logic: If there's any connected meter, show ONLY connected meters.
                    const hasAnyConnected = data.meter_status.some(s => {
                        const rs = (s.status || '').toLowerCase();
                        return rs === 'read_ok' || rs === 'prelogin_ok' || rs === 'connected' || rs === 'functional' || rs === 'reading';
                    });
                    
                    let filteredStatus = data.meter_status;
                    if (hasAnyConnected) {
                        filteredStatus = data.meter_status.filter(s => {
                            const rs = (s.status || '').toLowerCase();
                            return rs === 'read_ok' || rs === 'prelogin_ok' || rs === 'connected' || rs === 'functional' || rs === 'reading';
                        });
                    }

                    filteredStatus.forEach(status => {
                        const meterInfo = STATE.meters.find(m => m.meter_id == status.meter_id) || {};
                        const rawStatus = (status.status || '').toLowerCase();
                        const isConnected = rawStatus === 'read_ok' || rawStatus === 'prelogin_ok' || rawStatus === 'connected' || rawStatus === 'functional' || rawStatus === 'reading';
                        const isFailed = rawStatus.includes('failed') || rawStatus === 'disconnected' || rawStatus === 'idle';
                        
                        let displayStatus = isConnected ? 'Connected' : (rawStatus.includes('failed') ? 'Failed' : status.status);
                        const typeLabel = (meterInfo.type || 'N/A').toUpperCase().includes('DMI') ? 'EDMI' : (meterInfo.type || 'Meter');

                        const card = document.createElement('div');
                        card.className = 'activity-card';
                        card.innerHTML = `
                            <div class="meter-info">
                                <span class="meter-id">ID ${status.meter_id} - ${meterInfo.serial_number || 'N/A'} - ${typeLabel} ${meterInfo.meter_name || ''}</span>
                                <span class="status-label">Status</span>
                                <span class="status-value ${isConnected ? 'connected' : (isFailed ? 'failed' : '')}">${displayStatus}</span>
                            </div>
                            <div>
                                <span class="status-label">Raw Status</span><br/>
                                <span class="status-value">${status.status}</span>
                            </div>
                            <div class="timestamp">
                                <span class="status-label">Last Update</span><br/>
                                <span>${now.toLocaleTimeString()}</span>
                            </div>
                            <div class="timestamp">
                                <span class="status-label">Last Slot</span><br/>
                                <span>${now.toLocaleTimeString()}</span>
                            </div>
                        `;
                        elements.activityContainer.appendChild(card);
                    });
                }
            }

            // --- Energy Reports Logic ---
            const energyElements = {
                year: document.getElementById('energy-year-select'),
                month: document.getElementById('energy-month-select'),
                table: document.getElementById('energy-breakdown-body'),
                historyTable: document.getElementById('status-history-body'),
                total: document.getElementById('energy-total-to-lmv'),
                bess: document.getElementById('energy-bess-to-lmv'),
                rts: document.getElementById('energy-rts-to-lmv'),
                inq: document.getElementById('energy-inqualified')
            };

            async function fetchEnergyReport() {
                const y = energyElements.year.value;
                const m = energyElements.month.value;
                if (energyElements.table) {
                    energyElements.table.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:40px;"><div class="loader-ring" style="border-top-color:var(--primary-color)"></div></td></tr>';
                }

                try {
                    const sRes = await fetch(`${CONFIG.baseUrl}/energy/monthly-summary?year=${y}&month=${m}`);
                    const summary = await sRes.json();
                    if (summary.items && summary.items.length > 0) {
                        const item = summary.items[0];
                        energyElements.total.textContent = (item.total_energy_to_lmv_kwh || 0).toLocaleString(undefined, {minimumFractionDigits: 2}) + ' kWh';
                        energyElements.bess.textContent = (item.bess_to_lmv_energy_kwh || 0).toLocaleString(undefined, {minimumFractionDigits: 2}) + ' kWh';
                        energyElements.rts.textContent = (item.rfs_to_lmv_energy_kwh || 0).toLocaleString(undefined, {minimumFractionDigits: 2}) + ' kWh';
                        energyElements.inq.textContent = item.number_of_inqualified_intervals || 0;
                    }

                    const bRes = await fetch(`${CONFIG.baseUrl}/energy/monthly-breakdown?year=${y}&month=${m}`);
                    const breakdown = await bRes.json();
                    renderEnergyTable(breakdown.items);
                } catch (e) {
                    console.error('Energy Report Error:', e);
                    if (energyElements.table) {
                        energyElements.table.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:20px; color:var(--danger-color);">Error loading data.</td></tr>';
                    }
                }
            }

            async function fetchStatusHistory() {
                const y = energyElements.year.value;
                const m = energyElements.month.value;
                if (!energyElements.historyTable) return;
                
                energyElements.historyTable.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:40px;"><div class="loader-ring" style="border-top-color:var(--primary-color)"></div><p style="margin-top:10px; color:var(--text-secondary);">Loading status history...</p></td></tr>';

                try {
                    const response = await fetch(`${CONFIG.baseUrl}/faults/by-month?year=${y}&month=${m}`);
                    const data = await response.json();
                    STATE.historyData = data || [];
                    renderHistoryTable();
                } catch (e) {
                    console.error('Status History Error:', e);
                    energyElements.historyTable.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--danger-color);">Error loading history: ${e.message}</td></tr>`;
                }
            }

            function renderEnergyTable(items) {
                if (!items || items.length === 0) {
                    energyElements.table.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:20px;">No data available.</td></tr>';
                    return;
                }
                energyElements.table.innerHTML = items.map(item => {
                    const isFault = item.scenario_code !== 'ALL_OK';
                    const actionBtn = isFault ? `
                        <button class="btn-action view-fault-btn" 
                                data-start="${item.period_start}" 
                                data-end="${item.period_end}"
                                title="View faulty meters">
                            <i class="fa fa-eye"></i>
                        </button>
                    ` : '';
                    
                    const rowStyle = isFault ? 'style="background-color: #fee2e2;"' : '';
                    const mainVal = item.grid_energy_kwh || 0;
                    const bessVal = item.bess_to_lmv_kwh || 0;
                    const rtsVal = item.rts_to_lmv_kwh || 0;
                    const totalLmv = mainVal + bessVal + rtsVal;

                    return `
                    <tr ${rowStyle}>
                        <td>${new Date(item.period_start).toLocaleString()}</td>
                        <td>${new Date(item.period_end).toLocaleString()}</td>
                        <td><span class="scenario-pill ${item.scenario_code === 'ALL_OK' ? 'normal' : 'warning'}">${item.scenario_code}</span></td>
                        <td>${totalLmv.toFixed(2)}</td>
                        <td>${mainVal.toFixed(2)}</td>
                        <td>${(item.k_factor || 0).toFixed(2)}</td>
                        <td>${bessVal.toFixed(2)}</td>
                        <td>${rtsVal.toFixed(2)}</td>
                        <td style="text-align:center;">
                            ${actionBtn}
                        </td>
                    </tr>
                `; }).join('');

                // Add event listeners to buttons
                energyElements.table.querySelectorAll('.view-fault-btn').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const start = btn.getAttribute('data-start');
                        const end = btn.getAttribute('data-end');
                        showFaultInfo(start, end);
                    });
                });
            }

            function renderHistoryTable() {
                const scenarioWindows = STATE.historyData;
                if (!scenarioWindows || scenarioWindows.length === 0) {
                    energyElements.historyTable.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-secondary);">No history available for the selected period.</td></tr>';
                    return;
                }
                
                // Collect unique meters for filter
                const metersMap = new Map();
                let html = '';
                
                scenarioWindows.forEach(window => {
                    if (window.faults && window.faults.length > 0) {
                        window.faults.forEach(fault => {
                            // Populate filter map
                            metersMap.set(fault.meter_serial, fault.meter_name || 'N/A');

                            // Respect filter
                            if (STATE.selectedMeterFilter && String(fault.meter_serial) !== String(STATE.selectedMeterFilter)) return;

                             html += `
                                <tr style="vertical-align: middle;">
                                    <td style="padding:12px 16px; color:#64748b; vertical-align: middle; text-align: center;">${fault.meter_serial}</td>
                                    <td style="padding:12px 16px; font-weight:700; color:#001f8f; vertical-align: middle; text-align: center;">${fault.meter_name || 'N/A'}</td>
                                    <td style="padding:12px 16px; vertical-align: middle; text-align: center;"><span class="scenario-pill warning" style="font-size:10px;">${window.scenario_code}</span></td>
                                    <td style="padding:12px 16px; vertical-align: middle; text-align: center;">${new Date(fault.fault_start_ts).toLocaleString([], {year:'2-digit', month:'numeric', day:'numeric', hour:'numeric', minute:'2-digit'})}</td>
                                    <td style="padding:12px 16px; color:#64748b; vertical-align: middle; text-align: center;">${fault.fault_end_ts ? new Date(fault.fault_end_ts).toLocaleString([], {year:'2-digit', month:'numeric', day:'numeric', hour:'numeric', minute:'2-digit'}) : '--'}</td>
                                </tr>
                            `;
                        });
                    }
                });

                // Populate filter dropdown using ALL meters from STATE.meters
                const filterList = document.getElementById('meter-filter-list');
                if (filterList) {
                    const currentFilter = STATE.selectedMeterFilter;
                    let filterHtml = `<li><a href="javascript:void(0)" onclick="filterHistoryByMeter(null)">All Meters ${!currentFilter ? '✓' : ''}</a></li><li role="separator" class="divider"></li>`;
                    
                    // Sort meters by name
                    const sortedMeters = STATE.meters.map(m => [m.serial_number, m.meter_name || 'N/A']).sort((a, b) => a[1].localeCompare(b[1]));
                    
                    sortedMeters.forEach(([serial, name]) => {
                        const safeName = name.replace(/'/g, "\\'").replace(/"/g, '&quot;');
                        filterHtml += `<li><a href="javascript:void(0)" onclick="filterHistoryByMeter('${serial}', '${safeName}')">${name} - ${serial} ${currentFilter === serial ? '✓' : ''}</a></li>`;
                    });
                    filterList.innerHTML = filterHtml;
                }

                if (html === '') {
                    energyElements.historyTable.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:40px; color:var(--success-color);"><i class="fa fa-check-circle-o" style="font-size:30px; margin-bottom:10px;"></i><p>All meters were healthy for the selected period.</p></td></tr>';
                } else {
                    energyElements.historyTable.innerHTML = html;
                }
            }

            window.filterHistoryByMeter = function(serial, name) {
                STATE.selectedMeterFilter = serial;
                const btn = document.getElementById('filter-by-meter-btn');
                if (btn) {
                    btn.innerHTML = serial ? `Filter: ${name || serial} <span class="caret"></span>` : `Filter by Meter <span class="caret"></span>`;
                }
                renderHistoryTable();
            };

            function updateStats() {
                if (elements.statTotal) elements.statTotal.textContent = STATE.meters.length;
            }

            // --- Initialization ---
            function startPolling() {
                // Initial fetch
                fetchAllMeters();
                pollStatus();

                // Background polling
                setInterval(() => {
                    fetchAllMeters();
                    pollStatus();
                }, CONFIG.pollingInterval);
            }

            function init() {
                // Restore last status if available
                const lastStatus = localStorage.getItem('tariff_last_status');
                if (lastStatus) {
                    try {
                        const data = JSON.parse(lastStatus);
                        // We'll update the UI after meters are fetched/restored
                        setTimeout(() => updateStatusUI(data), 100);
                    } catch(e) {}
                }

                // Fetch metadata before main logic
                fetchRolesAndSources();

                startPolling();

                // Tab switching
                document.querySelectorAll('.tab-btn').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const tabId = btn.getAttribute('data-tab');
                        if (!tabId) return;

                        // Toggle Buttons
                        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                        btn.classList.add('active');

                        // Toggle Content
                        document.querySelectorAll('.tab-content').forEach(content => {
                            content.classList.remove('active');
                            if (content.id === `tab-${tabId}`) content.classList.add('active');
                        });

                        // Fetch data for the selected tab
                        if (tabId === 'monthly-analysis') fetchEnergyReport();
                        if (tabId === 'status-history') fetchStatusHistory();
                    });
                });

                // Auto-fetch on selector change
                if (energyElements.year) energyElements.year.addEventListener('change', () => {
                   fetchEnergyReport();
                   fetchStatusHistory();
                });
                if (energyElements.month) energyElements.month.addEventListener('change', () => {
                   fetchEnergyReport();
                   fetchStatusHistory();
                });

                // Export CSV Listener
                const exportBtn = document.getElementById('export-energy-csv');
                if (exportBtn) {
                    exportBtn.addEventListener('click', () => {
                        const y = parseInt(energyElements.year.value, 10);
                        const m = parseInt(energyElements.month.value, 10);

                        // Start date is 1st of month at 00:00:00
                        const start = new Date(y, m - 1, 1);
                        // End date is 1st of NEXT month at 00:00:00 (exclusive)
                        const end = new Date(y, m, 1);
                        
                        const formatDt = (date) => {
                            const pad = n => n.toString().padStart(2, '0');
                            return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
                        };
                        
                        const fromTs = encodeURIComponent(formatDt(start));
                        const toTs = encodeURIComponent(formatDt(end));
                        
                        const downloadUrl = `${CONFIG.baseUrl}/energy/interval-raw/csv?from_ts=${fromTs}&to_ts=${toTs}`;
                        window.open(downloadUrl, '_blank');
                    });
                }

                // Initial fetch for energy sub-tabs
                fetchEnergyReport();
                fetchStatusHistory();
            }

            init();
        })();
    

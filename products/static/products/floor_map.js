// Map functionality for location visualization

let map;
let activeFloor = 2;
let locationMarkers = {};
let mapVisible = false; // Track if map view is visible
let isDraggingMarker = false; // Flag to track marker dragging state
let mapInitialized = false; // Track if map has been initialized
    
// Initialize the map
function initMap() {
    const floorMapElement = document.getElementById('floorMap');
    if (!floorMapElement) {
        console.error('Map container not found');
        return;
    }
    
    const containerRect = floorMapElement.getBoundingClientRect();
    if (containerRect.width === 0 || containerRect.height === 0) {
        console.warn('Map container has no dimensions, retrying in 200ms...');
        setTimeout(initMap, 200);
        return;
    }
    
    // If map is already initialized, just invalidate size
    if (map && mapInitialized) {
        map.invalidateSize();
        return;
    }
    
    generateFloorButtons();
    
    // Create map with bounds for our virtual building
    // For PIC stream, use different zoom settings to maximize image
    const isPicStream = typeof currentStream !== 'undefined' && currentStream === 'PIC';
    
    map = L.map('floorMap', {
        crs: L.CRS.Simple, // Simple coordinate system for non-geographic maps
        minZoom: isPicStream ? -2 : -1,
        maxZoom: isPicStream ? 3 : 2,
        zoomControl: true
    });
    
    mapInitialized = true;
    
    // Use proper aspect ratio bounds for PIC stream to prevent stretching
    const bounds = isPicStream ? [[0, 0], [600, 800]] : [[0, 0], [100, 100]];
    
    // Create a canvas background with grid pattern
    const canvasSize = 1000;
    const canvas = document.createElement('canvas');
    canvas.width = canvasSize;
    canvas.height = canvasSize;
    const ctx = canvas.getContext('2d');
    
    // Fill background with different colors for RoadSide and LakeSide
    // LakeSide (left half)
    ctx.fillStyle = '#e3f0fa';  // Light blue for LakeSide
    ctx.fillRect(0, 0, canvasSize/2, canvasSize);
    
    // RoadSide (right half)
    ctx.fillStyle = '#f0f7e3';  // Light green for RoadSide
    ctx.fillRect(canvasSize/2, 0, canvasSize/2, canvasSize);
    
    // Draw grid lines
    ctx.strokeStyle = '#c0d8e8';
    ctx.lineWidth = 2;
    
    // Draw horizontal grid lines
    for(let y = 0; y <= canvasSize; y += 100) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvasSize, y);
        ctx.stroke();
    }
    
    // Draw vertical grid lines
    for(let x = 0; x <= canvasSize; x += 100) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvasSize);
        ctx.stroke();
    }
    
    // Draw division line between RoadSide and LakeSide
    ctx.strokeStyle = '#005fa3';
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(canvasSize/2, 0);
    ctx.lineTo(canvasSize/2, canvasSize);
    ctx.stroke();
    
    // Add labels for RoadSide and LakeSide
    ctx.fillStyle = '#005fa3';
    ctx.font = 'bold 36px Arial';
    ctx.textAlign = 'center';
    ctx.fillText('LakeSide', canvasSize/4, 50);
    ctx.fillText('RoadSide', 3*canvasSize/4, 50);
    
    // Add room outlines
    ctx.strokeStyle = '#005fa3';
    ctx.lineWidth = 3;
    
    // Room 1 - large office area
    ctx.strokeRect(100, 100, 600, 400);
    
    // Room 2 - small office or meeting room
    ctx.strokeRect(750, 100, 150, 200);
    
    // Room 3 - another small office
    ctx.strokeRect(750, 400, 150, 200);
    
    // Room 4 - storage or server room
    ctx.strokeRect(100, 600, 250, 300);
    
    // Room 5 - open workspace
    ctx.strokeRect(400, 600, 500, 300);
    
    // Add floor label
    ctx.fillStyle = '#005fa3';
    ctx.font = 'bold 48px Arial';
    ctx.textAlign = 'left';
    ctx.fillText('Floor ' + activeFloor, 50, 950);
    
    // Create a data URL from the canvas or use custom image for PIC stream
    let imageUrl = canvas.toDataURL();
    let opacity = 0.7;
    
    // Check if this is PIC stream and use Bay.png instead with full opacity
    if (typeof currentStream !== 'undefined' && currentStream === 'PIC') {
        imageUrl = '/static/floor_map/Bay.png';
        opacity = 1.0;
    }
    
    // Use the canvas image or custom image as our floor plan
    window.currentFloorPlan = L.imageOverlay(imageUrl, bounds, {
        opacity: opacity,
        interactive: false
    }).addTo(map);
    
    // Set view to center of bounds
    if (isPicStream) {
        // For PIC stream, fit bounds and allow zooming
        map.fitBounds(bounds);
    } else {
        map.fitBounds(bounds);
        map.setMaxBounds(bounds);
    }
    
    // Render markers for the initial floor
    renderFloorMarkers(activeFloor);
}

// Render markers for all locations (floor filtering disabled)
function renderFloorMarkers(floor) {
    clearMarkers();
    
    updateFloorPlan(floor);
    
    if (typeof currentStream !== 'undefined' && currentStream === 'PIC') {
        return;
    }
    
    Object.values(locationData).forEach(location => {
        // Create marker with style based on location type
        const locationType = location.type || getLocationType(location.name);
        let markerIcon = getMarkerIcon(locationType);
            
            let marker = L.marker(location.coords, {
                icon: markerIcon,
                draggable: true
            }).addTo(map);
            
            // Add click event to show location details - only if not currently dragging
            marker.on('click', function(e) {
                if (!isDraggingMarker) {
                    showLocationModal(location);
                }
            });
            
            // Handle marker drag start
            marker.on('dragstart', function() {
                isDraggingMarker = true;
            });
            
            // Handle marker drag end
            marker.on('dragend', function(e) {
                const newPos = marker.getLatLng();
                location.coords = [newPos.lat, newPos.lng];
                
                // Determine whether marker is on RoadSide or LakeSide
                const side = newPos.lng > 50 ? 'RoadSide' : 'LakeSide';
                
                // Update tooltip to show the side
                marker.setTooltipContent(`${location.name}<br><small>(${side})</small>`);
                
                // Reset dragging flag with a small delay to prevent click event from firing
                setTimeout(() => {
                    isDraggingMarker = false;
                }, 100);
            });
            
            // Add tooltip with location name
            const side = location.coords[1] > 50 ? 'RoadSide' : 'LakeSide';
            marker.bindTooltip(`${location.name}<br><small>(${side})</small>`, {
                permanent: false,
                direction: 'top',
                className: 'location-tooltip'
            });
            
            locationMarkers[location.id] = marker;
    });
}

// Get appropriate marker icon based on location type
function getMarkerIcon(type) {
    let color, iconClass;
    
    switch(type) {
        case 'bay':
            color = '#28a745'; // Green
            iconClass = 'fa-cubes';
            break;
        case 'system':
            color = '#dc3545'; // Red
            iconClass = 'fa-server';
            break;
        case 'desktop':
            color = '#ffc107'; // Yellow
            iconClass = 'fa-desktop';
            break;
        default:
            color = '#17a2b8'; // Blue
            iconClass = 'fa-map-marker-alt';
    }
    
    return L.divIcon({
        html: `<div style="background-color:${color};color:white;border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 5px rgba(0,0,0,0.3);"><i class="fas ${iconClass}"></i></div>`,
        className: 'location-marker-icon',
        iconSize: [30, 30],
        iconAnchor: [15, 15]
    });
}

// Clear all markers from the map
function clearMarkers() {
    Object.values(locationMarkers).forEach(marker => {
        if (map) {
            map.removeLayer(marker);
        }
    });
    locationMarkers = {};
}

// Generate floor buttons - disabled since floor filtering is not used
function generateFloorButtons() {
    // Floor buttons are disabled - all locations shown on single map
    return;
}

// Update floor buttons to highlight active floor - disabled
function updateFloorButtons(activeFloor) {
    // Floor buttons are disabled
    return;
}

// Show location details modal
function showLocationModal(location) {
    const modal = document.getElementById('locationModal');
    const nameElement = document.getElementById('modalLocationName');
    const addressElement = document.getElementById('modalLocationAddress');
    const actionsElement = document.getElementById('modalActionButtons');
    
    // Determine side (RoadSide or LakeSide)
    const side = location.coords[1] > 50 ? 'RoadSide' : 'LakeSide';
    
    // Populate modal with location details
    nameElement.textContent = location.name;
    addressElement.innerHTML = `${location.address}<br><span style="color:#005fa3;font-weight:600;margin-top:5px;display:inline-block;"><i class="fas fa-map-pin"></i> ${side} Area</span>`;
    
    // Hide the actions section as per requirement
    if (actionsElement) {
        actionsElement.style.display = 'none';
    }
    
    // Show modal
    modal.style.display = 'flex';
    modal.querySelector('.modal-content').classList.remove('animate__fadeOutDown');
    modal.querySelector('.modal-content').classList.add('animate__fadeInUp');
}

// Close location details modal
function closeLocationModal() {
    const modal = document.getElementById('locationModal');
    modal.querySelector('.modal-content').classList.remove('animate__fadeInUp');
    modal.querySelector('.modal-content').classList.add('animate__fadeOutDown');
    
    setTimeout(() => {
        modal.style.display = 'none';
    }, 500);
}

// Helper function: Extract floor number from location name
function getFloorFromName(name) {
    name = name.toLowerCase();
    
    // Check for common floor naming patterns
    const floorPatterns = [
        { pattern: /\b(\d+)(st|nd|rd|th)\s+floor\b/i, group: 1 },
        { pattern: /\bfloor\s+(\d+)\b/i, group: 1 },
        { pattern: /\bf(\d+)\b/i, group: 1 },
        { pattern: /\b(\d+)f\b/i, group: 1 }
    ];
    
    for (const {pattern, group} of floorPatterns) {
        const match = name.match(pattern);
        if (match && match[group]) {
            return parseInt(match[group]);
        }
    }
    
    // Explicit checks for common floor names
    if (name.includes("ground floor") || name.includes("g floor")) return 0;
    if (name.includes("1st floor") || name.includes("first floor")) return 1;
    if (name.includes("2nd floor") || name.includes("second floor")) return 2;
    if (name.includes("3rd floor") || name.includes("third floor")) return 3;
    if (name.includes("4th floor") || name.includes("fourth floor")) return 4;
    if (name.includes("5th floor") || name.includes("fifth floor")) return 5;
    
    // Default floor if not specified
    return 1;
}

// Helper function: Determine location type based on name
function getLocationType(name) {
    name = name.toLowerCase();
    if (name.includes("bay")) return "bay";
    if (name.includes("desktop")) return "desktop";
    if (name.includes("full system")) return "system";
    // Default type
    return "bay";
}

// Helper function: Generate random coordinates for demo
function getRandomCoordinates() {
    // Generate random coordinates within floor boundaries
    // For demo, we'll use a 0-100 range to represent a floor plan
    return [
        20 + Math.random() * 60, // X coordinate (20-80% of width)
        20 + Math.random() * 60  // Y coordinate (20-80% of height)
    ];
}

// Update floor plan for the current active floor
function updateFloorPlan(floor) {
    if (!map) return;
    
    if (window.currentFloorPlan) {
        map.removeLayer(window.currentFloorPlan);
    }
    
    // Create a new canvas for this floor
    const canvasSize = 1000;
    const canvas = document.createElement('canvas');
    canvas.width = canvasSize;
    canvas.height = canvasSize;
    const ctx = canvas.getContext('2d');
    
    // Fill background with different colors for RoadSide and LakeSide
    // LakeSide (left half)
    ctx.fillStyle = '#e3f0fa';  // Light blue for LakeSide
    ctx.fillRect(0, 0, canvasSize/2, canvasSize);
    
    // RoadSide (right half)
    ctx.fillStyle = '#f0f7e3';  // Light green for RoadSide
    ctx.fillRect(canvasSize/2, 0, canvasSize/2, canvasSize);
    
    // Draw grid lines
    ctx.strokeStyle = '#c0d8e8';
    ctx.lineWidth = 2;
    
    // Draw horizontal grid lines
    for(let y = 0; y <= canvasSize; y += 100) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvasSize, y);
        ctx.stroke();
    }
    
    // Draw vertical grid lines
    for(let x = 0; x <= canvasSize; x += 100) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvasSize);
        ctx.stroke();
    }
    
    // Draw division line between RoadSide and LakeSide
    ctx.strokeStyle = '#005fa3';
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(canvasSize/2, 0);
    ctx.lineTo(canvasSize/2, canvasSize);
    ctx.stroke();
    
    // Add labels for RoadSide and LakeSide
    ctx.fillStyle = '#005fa3';
    ctx.font = 'bold 36px Arial';
    ctx.textAlign = 'center';
    ctx.fillText('LakeSide', canvasSize/4, 50);
    ctx.fillText('RoadSide', 3*canvasSize/4, 50);
    
    // Draw room layouts
    ctx.strokeStyle = '#005fa3';
    ctx.lineWidth = 3;
    
    // Room areas
    ctx.strokeRect(100, 100, 300, 300); // Room 1
    ctx.strokeRect(600, 100, 300, 300); // Room 2
    ctx.strokeRect(100, 500, 400, 200); // Room 3
    ctx.strokeRect(550, 500, 350, 200); // Room 4
    
    ctx.fillStyle = '#005fa3';
    ctx.font = 'bold 48px Arial';
    ctx.textAlign = 'left';
    ctx.fillText('Location Map', 50, 950);
    
    // Create a data URL from the canvas or use custom image for PIC stream
    let imageUrl = canvas.toDataURL();
    const isPicStream = typeof currentStream !== 'undefined' && currentStream === 'PIC';
    const bounds = isPicStream ? [[0, 0], [600, 800]] : [[0, 0], [100, 100]];
    let opacity = 0.7;
    
    // Check if this is PIC stream and use Bay.png instead with full opacity
    if (typeof currentStream !== 'undefined' && currentStream === 'PIC') {
        imageUrl = '/static/floor_map/Bay.png';
        opacity = 1.0;
    }
    
    // Use the canvas image or custom image as our floor plan
    window.currentFloorPlan = L.imageOverlay(imageUrl, bounds, {
        opacity: opacity,
        interactive: false
    }).addTo(map);
}

// Setup map functionality when ready
document.addEventListener('DOMContentLoaded', function() {
    const toggleMapViewBtn = document.getElementById('toggleMapView');
    const mapView = document.getElementById('mapView');
    const tableView = document.getElementById('tableView');
    const cardView = document.getElementById('cardView');
    const toggleViewBtn = document.getElementById('toggleView');
    
    // Initialize mapVisible variable based on the actual display state
    mapVisible = mapView && window.getComputedStyle(mapView).display === 'block';
    
    // Update the toggle button icon to match the current state
    if (toggleMapViewBtn) {
        toggleMapViewBtn.querySelector('i').className = mapVisible ? 'fas fa-times' : 'fas fa-map';
        if (mapVisible) {
            toggleMapViewBtn.classList.add('active');
        }
    }
    
    if (toggleMapViewBtn) {
        // Important: Remove any existing click event listeners first
        const toggleMapViewBtnClone = toggleMapViewBtn.cloneNode(true);
        if (toggleMapViewBtn.parentNode) {
            toggleMapViewBtn.parentNode.replaceChild(toggleMapViewBtnClone, toggleMapViewBtn);
        }
        
        // Add our click event listener to the cloned button
        toggleMapViewBtnClone.addEventListener('click', function() {
            console.log("Map toggle clicked. Current state:", mapVisible);
            
            // Toggle map visibility
            if (mapVisible) {
                // If map is already visible, hide it and show the previous view
                mapView.style.display = 'none';
                
                // Show the previously active view (table or card)
                if (toggleViewBtn && toggleViewBtn.querySelector('i').className.includes('list')) {
                    cardView.style.display = 'block';
                } else {
                    tableView.style.display = 'block';
                }
                
                mapVisible = false;
                console.log("Map hidden. mapVisible =", mapVisible);
                
                // Update icon and remove active class
                this.querySelector('i').className = 'fas fa-map';
                this.classList.remove('active');
            } else {
                // Hide table and card views, show map view
                tableView.style.display = 'none';
                cardView.style.display = 'none';
                mapView.style.display = 'block';
                
                mapVisible = true;
                console.log("Map shown. mapVisible =", mapVisible);
                
                // Update icon and add active class
                this.querySelector('i').className = 'fas fa-times';
                this.classList.add('active');
                
                // Remove active class from toggle view button
                if (toggleViewBtn) {
                    toggleViewBtn.classList.remove('active');
                }
                
                // Generate location data from DOM if it exists in window context
                if (typeof populateLocationData === 'function') {
                    populateLocationData();
                }
                
                // Initialize map if not already done
                if (!mapInitialized) {
                    setTimeout(() => {
                        initMap();
                    }, 100);
                } else if (map) {
                    // Invalidate map size to fix rendering issues
                    setTimeout(() => {
                        map.invalidateSize();
                    }, 100);
                }
            }
        });
    }
    
    document.querySelectorAll('.floor-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const floor = parseInt(this.getAttribute('data-floor'));
            activeFloor = floor;
            renderFloorMarkers(floor);
        });
    });
    
    const closeModalBtn = document.querySelector('.close-modal');
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', closeLocationModal);
    }
    
    // Close modal when clicking outside of it
    const locationModal = document.getElementById('locationModal');
    if (locationModal) {
        locationModal.addEventListener('click', function(event) {
            if (event.target === this) {
                closeLocationModal();
            }
        });
    }
});

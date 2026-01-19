// filepath: c:\Users\320268488\OneDrive - Philips\Documents\Hackathon\products\static\products\floor_map.js
// Map functionality for location visualization

// Initialize map-related variables
let map;
let activeFloor = 2; // Default to 2nd floor
let locationMarkers = {};
let mapVisible = false; // Track if map view is visible
let isDraggingMarker = false; // Flag to track marker dragging state
    
// Initialize the map
function initMap() {
    if (!document.getElementById('floorMap')) {
        console.error('Map container not found');
        return;
    }
    
    // Get unique floors from location data
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
    
    // Define map bounds
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
        opacity = 1.0; // Maximum opacity for PIC stream
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

// Render markers for a specific floor
function renderFloorMarkers(floor) {
    // Clear any existing markers
    clearMarkers();
    
    // Update the floor plan to show current floor
    updateFloorPlan(floor);
    
    // Skip adding markers for PIC stream
    if (typeof currentStream !== 'undefined' && currentStream === 'PIC') {
        updateFloorButtons(floor);
        return;
    }
    
    // Add markers for all locations on the current floor
    Object.values(locationData).forEach(location => {
        // Extract floor from location name
        const locationFloor = getFloorFromName(location.name);
        
        if (locationFloor === floor) {
            // Create marker with style based on location type
            const locationType = location.type || getLocationType(location.name);
            let markerIcon = getMarkerIcon(locationType);
            
            let marker = L.marker(location.coords, {
                icon: markerIcon,
                draggable: true // Make marker draggable
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
                location.coords = [newPos.lat, newPos.lng]; // Update coordinates in data
                
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
            
            // Store marker reference for later removal
            locationMarkers[location.id] = marker;
        }
    });
    
    // Update active floor button styling
    updateFloorButtons(floor);
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

// Generate floor buttons based on location data
function generateFloorButtons() {
    // Get unique floors from locations
    const floors = [];
    const floorSet = new Set();
    
    // Extract floor numbers from locationData
    Object.values(locationData).forEach(location => {
        // Extract floor from the name
        const floorNum = getFloorFromName(location.name);
        if (!floorSet.has(floorNum)) {
            floors.push(floorNum);
            floorSet.add(floorNum);
        }
    });
    
    // If no floors were found, add default floors
    if (floors.length === 0) {
        floors.push(1, 2, 3);
    }
    
    // Sort floors numerically
    floors.sort((a, b) => a - b);
    
    // Get the floor controls container
    const floorControls = document.querySelector('.floor-controls');
    if (!floorControls) return;
    
    // Clear existing buttons
    floorControls.innerHTML = '';
    
    // Create a button for each floor
    floors.forEach(floor => {
        const btn = document.createElement('button');
        btn.className = 'floor-btn';
        btn.setAttribute('data-floor', floor);
        
        // Add the ordinal suffix
        let suffix = 'th';
        if (floor % 10 === 1 && floor % 100 !== 11) suffix = 'st';
        else if (floor % 10 === 2 && floor % 100 !== 12) suffix = 'nd';
        else if (floor % 10 === 3 && floor % 100 !== 13) suffix = 'rd';
        
        btn.textContent = `${floor}${suffix} Floor`;
        
        // Add click event
        btn.addEventListener('click', function() {
            const floorNum = parseInt(this.getAttribute('data-floor'));
            activeFloor = floorNum;
            renderFloorMarkers(floorNum);
        });
        
        floorControls.appendChild(btn);
    });
    
    // Set the first button as active
    if (floors.length > 0) {
        activeFloor = floors[0];
        const firstBtn = floorControls.querySelector('.floor-btn');
        if (firstBtn) {
            firstBtn.classList.add('active');
        }
    }
}

// Update floor buttons to highlight active floor
function updateFloorButtons(activeFloor) {
    document.querySelectorAll('.floor-btn').forEach(btn => {
        const floor = parseInt(btn.getAttribute('data-floor'));
        if (floor === activeFloor) {
            btn.style.background = '#005fa3';
            btn.style.color = 'white';
        } else {
            btn.style.background = '#e3f0fa';
            btn.style.color = '#005fa3';
        }
    });
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
    
    // Remove the existing floor plan if it exists
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
    
    // Draw room layouts that might differ by floor
    ctx.strokeStyle = '#005fa3';
    ctx.lineWidth = 3;
    
    // Rooms that appear on all floors
    ctx.strokeRect(100, 100, 300, 300); // Common room 1
    ctx.strokeRect(600, 100, 300, 300); // Common room 2
    
    // Floor-specific rooms
    if (floor === 1 || floor === 2) {
        // Lower floors have more divided spaces
        ctx.strokeRect(100, 500, 200, 200);
        ctx.strokeRect(350, 500, 300, 200);
        ctx.strokeRect(700, 500, 200, 200);
    } else if (floor === 3 || floor === 4) {
        // Middle floors have medium divisions
        ctx.strokeRect(100, 500, 400, 200);
        ctx.strokeRect(550, 500, 350, 200);
    } else {
        // Higher floors have more open plans
        ctx.strokeRect(100, 500, 800, 200);
    }
    
    // Add floor specific text
    let floorDescription = '';
    switch(floor) {
        case 1:
            floorDescription = '';
            break;
        case 2:
            floorDescription = '';
            break;
        case 3:
            floorDescription = '';
            break;
        case 4:
            floorDescription = '';
            break;
        default:
            floorDescription = '';
    }
    
    // Add floor label with description
    ctx.fillStyle = '#005fa3';
    ctx.font = 'bold 48px Arial';
    ctx.textAlign = 'left';
    ctx.fillText(`Floor ${floor}  ${floorDescription}`, 50, 950);
    
    // Create a data URL from the canvas or use custom image for PIC stream
    let imageUrl = canvas.toDataURL();
    const isPicStream = typeof currentStream !== 'undefined' && currentStream === 'PIC';
    const bounds = isPicStream ? [[0, 0], [600, 800]] : [[0, 0], [100, 100]];
    let opacity = 0.7;
    
    // Check if this is PIC stream and use Bay.png instead with full opacity
    if (typeof currentStream !== 'undefined' && currentStream === 'PIC') {
        imageUrl = '/static/floor_map/Bay.png';
        opacity = 1.0; // Maximum opacity for PIC stream
    }
    
    // Use the canvas image or custom image as our floor plan
    window.currentFloorPlan = L.imageOverlay(imageUrl, bounds, {
        opacity: opacity,
        interactive: false
    }).addTo(map);
}

// Setup map functionality when ready
document.addEventListener('DOMContentLoaded', function() {
    // Set up map view button
    const toggleMapViewBtn = document.getElementById('toggleMapView');
    const mapView = document.getElementById('mapView');
    const tableView = document.getElementById('tableView');
    const cardView = document.getElementById('cardView');
    
    // Initialize mapVisible variable based on the actual display state
    mapVisible = mapView && window.getComputedStyle(mapView).display === 'block';
    
    // Update the toggle button icon to match the current state
    if (toggleMapViewBtn) {
        toggleMapViewBtn.querySelector('i').className = mapVisible ? 'fas fa-times' : 'fas fa-map';
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
                if (document.getElementById('toggleView').querySelector('i').className.includes('list')) {
                    cardView.style.display = 'block';
                } else {
                    tableView.style.display = 'block';
                }
                
                mapVisible = false;
                console.log("Map hidden. mapVisible =", mapVisible);
                
                // Update icon to reflect that map can be opened
                this.querySelector('i').className = 'fas fa-map';
            } else {
                // Hide table and card views, show map view
                tableView.style.display = 'none';
                cardView.style.display = 'none';
                mapView.style.display = 'block';
                
                mapVisible = true;
                console.log("Map shown. mapVisible =", mapVisible);
                
                // Update icon to reflect that map can be closed
                this.querySelector('i').className = 'fas fa-times';
                
                // Generate location data from DOM if it exists in window context
                if (typeof populateLocationData === 'function') {
                    populateLocationData();
                }
                
                // Initialize map if not already done
                if (!map) {
                    setTimeout(() => {
                        initMap();
                    }, 100);
                }
            }
        });
    }
    
    // Set up floor selection buttons
    document.querySelectorAll('.floor-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const floor = parseInt(this.getAttribute('data-floor'));
            activeFloor = floor;
            renderFloorMarkers(floor);
        });
    });
    
    // Set up modal close button
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

// ============================================================
// ABC BUSINESS MANAGER - SERVICE WORKER
// PWA + CATÁLOGO OFFLINE
// ============================================================
//
// MODO ONLINE:
// ABC funciona normalmente.
//
// MODO OFFLINE:
// - Si se intenta abrir cualquier parte normal de ABC,
//   muestra una pantalla offline.
// - Desde esa pantalla se puede abrir el catálogo guardado.
// - El catálogo conserva búsqueda, filtros y calculadoras.
//
// NO guarda ni permite modificar offline:
// - pedidos
// - clientes
// - inventario
// - compras
// - producción
// - finanzas
// - configuración
// - formularios POST
// ============================================================


const CACHE_STATIC = "abc-static-v3";
const CACHE_CATALOGO = "abc-catalogo-v3";


// ============================================================
// ARCHIVOS ESTÁTICOS
// ============================================================

const STATIC_ASSETS = [

    "/static/manifest.json",

    "/static/icons/favicon-64.png",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",

    "/static/uploads/logo_abc.png"

];


// ============================================================
// PANTALLA OFFLINE
// ============================================================

const PAGINA_OFFLINE = `

<!DOCTYPE html>

<html lang="es">

<head>

    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <meta
        name="theme-color"
        content="#051041"
    >

    <title>
        ABC Business Manager
    </title>


    <style>

        * {
            box-sizing: border-box;
        }


        body {

            margin: 0;

            min-height: 100vh;

            display: flex;

            align-items: center;
            justify-content: center;

            padding: 22px;

            font-family:
                Arial,
                sans-serif;

            background:
                #f5f7fb;

            color:
                #202331;

        }


        .offline-card {

            width: 100%;

            max-width: 430px;

            padding: 30px;

            background:
                #ffffff;

            border:
                1px solid
                #e1e6ef;

            border-radius:
                16px;

            box-shadow:
                0 12px 35px
                rgba(
                    5,
                    16,
                    65,
                    0.10
                );

            text-align:
                center;

        }


        .offline-logo {

            width: 90px;

            height: 90px;

            object-fit:
                contain;

            margin-bottom:
                15px;

        }


        h1 {

            margin:
                0 0 8px;

            color:
                #0a205c;

            font-size:
                23px;

        }


        .estado {

            display:
                inline-block;

            margin:
                12px 0 18px;

            padding:
                7px 11px;

            border-radius:
                20px;

            background:
                #fff4dc;

            color:
                #805b0c;

            font-size:
                12px;

            font-weight:
                700;

        }


        .descripcion {

            margin:
                0 0 23px;

            color:
                #697386;

            font-size:
                14px;

            line-height:
                1.55;

        }


        .catalogo-btn {

            display:
                block;

            width:
                100%;

            padding:
                13px 15px;

            border-radius:
                9px;

            background:
                #051041;

            color:
                #ffffff;

            text-decoration:
                none;

            font-size:
                14px;

            font-weight:
                700;

        }


        .catalogo-btn:active {

            transform:
                scale(0.99);

        }


        .nota {

            margin-top:
                18px;

            color:
                #9299a8;

            font-size:
                11px;

            line-height:
                1.45;

        }

    </style>

</head>


<body>


    <div class="offline-card">


        <img
            src="/static/uploads/logo_abc.png"
            class="offline-logo"
            alt="ABC"
        >


        <h1>
            ABC Business Manager
        </h1>


        <div class="estado">
            🟠 Sin conexión
        </div>


        <p class="descripcion">

            No hay conexión a Internet.

            <br><br>

            Las funciones administrativas de ABC
            necesitan conexión, pero puedes consultar
            la última versión guardada de tu catálogo
            de precios.

        </p>


        <a
            href="/catalogo/"
            class="catalogo-btn"
        >
            📖 Abrir catálogo offline
        </a>


        <p class="nota">

            Pedidos, inventario, compras, producción
            y finanzas estarán disponibles nuevamente
            cuando recuperes la conexión.

        </p>


    </div>


</body>

</html>

`;


// ============================================================
// INSTALACIÓN
// ============================================================

self.addEventListener(

    "install",

    function (event) {

        event.waitUntil(

            caches
                .open(
                    CACHE_STATIC
                )
                .then(
                    function (cache) {

                        return cache.addAll(
                            STATIC_ASSETS
                        );

                    }
                )

        );


        self.skipWaiting();

    }

);


// ============================================================
// ACTIVACIÓN
// ============================================================

self.addEventListener(

    "activate",

    function (event) {


        const cachesPermitidos = [

            CACHE_STATIC,
            CACHE_CATALOGO

        ];


        event.waitUntil(

            caches
                .keys()
                .then(
                    function (keys) {

                        return Promise.all(

                            keys.map(

                                function (key) {

                                    if (
                                        !cachesPermitidos.includes(
                                            key
                                        )
                                    ) {

                                        return caches.delete(
                                            key
                                        );

                                    }

                                }

                            )

                        );

                    }
                )
                .then(
                    function () {

                        return self.clients.claim();

                    }
                )

        );

    }

);


// ============================================================
// SOLICITUDES
// ============================================================

self.addEventListener(

    "fetch",

    function (event) {


        const request =
            event.request;


        // ====================================================
        // SOLO GET
        // ====================================================

        if (
            request.method
            !== "GET"
        ) {

            return;

        }


        const url =
            new URL(
                request.url
            );


        // ====================================================
        // SOLO ABC
        // ====================================================

        if (
            url.origin
            !== self.location.origin
        ) {

            return;

        }


        // ====================================================
        // ARCHIVOS ESTÁTICOS
        // ====================================================

        if (
            url.pathname.startsWith(
                "/static/"
            )
        ) {

            event.respondWith(

                caches
                    .match(
                        request
                    )
                    .then(

                        function (cached) {


                            if (cached) {

                                return cached;

                            }


                            return fetch(
                                request
                            )
                            .then(

                                function (response) {


                                    if (
                                        !response
                                        || !response.ok
                                    ) {

                                        return response;

                                    }


                                    const copia =
                                        response.clone();


                                    caches
                                        .open(
                                            CACHE_STATIC
                                        )
                                        .then(

                                            function (cache) {

                                                cache.put(
                                                    request,
                                                    copia
                                                );

                                            }

                                        );


                                    return response;

                                }

                            );

                        }

                    )

            );


            return;

        }


        // ====================================================
        // CATÁLOGO
        // ====================================================
        //
        // Primero intenta Internet.
        //
        // Si funciona:
        // guarda la versión nueva.
        //
        // Si falla:
        // muestra la última copia guardada.
        // ====================================================

        if (
            url.pathname === "/catalogo/"
            ||
            url.pathname === "/catalogo"
        ) {

            event.respondWith(

                fetch(
                    request
                )

                .then(

                    function (response) {


                        // ------------------------------------
                        // GUARDAR SOLO CATÁLOGO REAL
                        // ------------------------------------

                        if (
                            response.ok
                            &&
                            !response.redirected
                            &&
                            response.type === "basic"
                        ) {


                            const copia =
                                response.clone();


                            caches
                                .open(
                                    CACHE_CATALOGO
                                )
                                .then(

                                    function (cache) {

                                        return cache.put(
                                            "/catalogo/",
                                            copia
                                        );

                                    }

                                );

                        }


                        return response;

                    }

                )


                // --------------------------------------------
                // SIN INTERNET
                // --------------------------------------------

                .catch(

                    function () {


                        return caches
                            .open(
                                CACHE_CATALOGO
                            )
                            .then(

                                function (cache) {

                                    return cache.match(
                                        "/catalogo/"
                                    );

                                }

                            )
                            .then(

                                function (cached) {


                                    if (cached) {

                                        return cached;

                                    }


                                    // Nunca se abrió el catálogo
                                    // anteriormente con Internet.

                                    return new Response(

                                        PAGINA_OFFLINE.replace(

                                            `
                                            <a
                                                href="/catalogo/"
                                                class="catalogo-btn"
                                            >
                                                📖 Abrir catálogo offline
                                            </a>
                                            `,

                                            `
                                            <div
                                                style="
                                                    padding: 13px;
                                                    border-radius: 9px;
                                                    background: #eef1f7;
                                                    color: #687186;
                                                    font-size: 13px;
                                                "
                                            >
                                                📖 El catálogo todavía
                                                no se ha guardado en
                                                este dispositivo.
                                            </div>
                                            `

                                        ),

                                        {

                                            headers: {

                                                "Content-Type":
                                                    "text/html; charset=utf-8"

                                            }

                                        }

                                    );

                                }

                            );

                    }

                )

            );


            return;

        }


        // ====================================================
        // RESTO DE ABC
        // ====================================================
        //
        // Online:
        // funcionamiento normal.
        //
        // Offline:
        // pantalla con acceso al catálogo.
        //
        // ====================================================

        if (
            request.mode
            === "navigate"
        ) {

            event.respondWith(

                fetch(
                    request
                )

                .catch(

                    function () {

                        return new Response(

                            PAGINA_OFFLINE,

                            {

                                headers: {

                                    "Content-Type":
                                        "text/html; charset=utf-8"

                                }

                            }

                        );

                    }

                )

            );

        }

    }

);
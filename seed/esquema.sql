-- Esquema de ms-presupuestos. Se aplica IGUAL en los 3 schemas de tenant
-- (t_acme, t_globex, t_initech) dentro de la database ppm_presupuestos.

-- ---------------------------------------------------------------- presupuestos
-- Uno por proyecto. Lo CREA EL WORKER cuando llega proyecto.creado, en 0:
-- nadie lo pide por HTTP. Despues el PMO lo aprueba con un monto.
CREATE TABLE IF NOT EXISTS presupuestos (
    id              BIGSERIAL PRIMARY KEY,
    proyecto_id     BIGINT      NOT NULL UNIQUE,  -- logico, de ms-portafolios
    codigo_proyecto TEXT,
    nombre_proyecto TEXT,
    monto_aprobado  NUMERIC(14,2) NOT NULL DEFAULT 0,
    moneda          TEXT        NOT NULL DEFAULT 'PEN',
    estado          TEXT        NOT NULL DEFAULT 'borrador',
    aprobado_por    UUID,
    aprobado_en     TIMESTAMPTZ,
    -- Se mantiene al dia con cada gasto para no recalcular la suma en cada
    -- lectura: con 7,000 gastos por tenant el SUM() en caliente se nota.
    total_gastado   NUMERIC(14,2) NOT NULL DEFAULT 0,
    alerta_enviada  BOOLEAN     NOT NULL DEFAULT FALSE,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (estado IN ('borrador', 'aprobado', 'cerrado')),
    CHECK (monto_aprobado >= 0)
);

CREATE INDEX IF NOT EXISTS ix_presupuestos_proyecto ON presupuestos (proyecto_id);

-- -------------------------------------------------------------------- partidas
-- Las categorias en las que se divide un presupuesto.
CREATE TABLE IF NOT EXISTS partidas (
    id              BIGSERIAL PRIMARY KEY,
    presupuesto_id  BIGINT      NOT NULL REFERENCES presupuestos(id) ON DELETE CASCADE,
    nombre          TEXT        NOT NULL,
    monto_asignado  NUMERIC(14,2) NOT NULL DEFAULT 0,
    UNIQUE (presupuesto_id, nombre)
);

-- ---------------------------------------------------------------------- gastos
CREATE TABLE IF NOT EXISTS gastos (
    id              BIGSERIAL PRIMARY KEY,
    presupuesto_id  BIGINT      NOT NULL REFERENCES presupuestos(id) ON DELETE CASCADE,
    partida_id      BIGINT      REFERENCES partidas(id) ON DELETE SET NULL,
    concepto        TEXT        NOT NULL,
    monto           NUMERIC(14,2) NOT NULL,
    fecha           DATE        NOT NULL DEFAULT CURRENT_DATE,
    proveedor       TEXT,
    -- Key del comprobante en el bucket S3 de adjuntos, prefijada por tenant
    comprobante_key TEXT,
    registrado_por  UUID,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (monto > 0)
);

CREATE INDEX IF NOT EXISTS ix_gastos_presupuesto ON gastos (presupuesto_id, fecha DESC);

-- --------------------------------------------------------- proyecciones_costo
-- Costo proyectado de horas-hombre. Lo escribe el WORKER cuando ms-recursos
-- publica recurso.asignado: este microservicio no conoce a ms-recursos.
CREATE TABLE IF NOT EXISTS proyecciones_costo (
    id              BIGSERIAL PRIMARY KEY,
    presupuesto_id  BIGINT      NOT NULL REFERENCES presupuestos(id) ON DELETE CASCADE,
    recurso_id      UUID        NOT NULL,
    horas_semana    NUMERIC(6,2) NOT NULL,
    costo_hora      NUMERIC(10,2) NOT NULL,
    semanas         INTEGER     NOT NULL DEFAULT 1,
    costo_proyectado NUMERIC(14,2) GENERATED ALWAYS AS
                        (horas_semana * costo_hora * semanas) STORED,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (presupuesto_id, recurso_id)
);

-- --------------------------------------------------------- eventos_procesados
CREATE TABLE IF NOT EXISTS eventos_procesados (
    evento_id    UUID PRIMARY KEY,
    tipo         TEXT NOT NULL,
    procesado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------- vista
-- La ejecucion presupuestal, que es LA pregunta del producto: cuanto se
-- aprobo, cuanto se gasto y cuanto queda.
CREATE OR REPLACE VIEW ejecucion AS
SELECT  p.id,
        p.proyecto_id,
        p.codigo_proyecto,
        p.nombre_proyecto,
        p.monto_aprobado,
        p.total_gastado,
        p.monto_aprobado - p.total_gastado            AS saldo,
        CASE WHEN p.monto_aprobado > 0
             THEN ROUND(100 * p.total_gastado / p.monto_aprobado, 2)
             ELSE 0 END                               AS ejecutado_pct,
        p.estado,
        p.alerta_enviada,
        (SELECT COUNT(*) FROM gastos g WHERE g.presupuesto_id = p.id) AS n_gastos
FROM    presupuestos p;

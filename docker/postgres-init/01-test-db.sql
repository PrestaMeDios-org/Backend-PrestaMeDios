-- Base de los tests de integración (el nombre debe contener "test"; el fixture la recrea).
-- Sólo corre la primera vez que se crea el volumen `pgdata` (SPEC-11 §4.3).
CREATE DATABASE prestamedios_test;

// CI en Jenkins: el mismo trabajo que .github/workflows/ci.yml y security-scan.yml.
pipeline {
    agent {
        // Imagen propia del agente: Python 3.14 + uv 0.13.8 + zsh.
        dockerfile {
            dir 'ci/jenkins'
            filename 'Dockerfile'
            // Con --init, PID 1 recoge los procesos huérfanos como en un runner
            // normal. Sin él, los nietos que matan los tests quedan zombis y
            // siguen pareciendo vivos.
            args '--init'
        }
    }

    options {
        timeout(time: 20, unit: 'MINUTES')
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        CI = 'true'
        // Usa el Python 3.14 de la imagen; nada de descargar intérpretes.
        UV_PYTHON_DOWNLOADS = 'never'
    }

    stages {
        // Va primero, con el árbol recién clonado (como el job aparte de GitHub).
        // Si falla, el build queda en FAILURE pero las demás etapas se ejecutan.
        stage('Seguridad') {
            steps {
                catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
                    sh '''#!/usr/bin/env bash
                        set -euo pipefail
                        for scanner in scripts/security/scan_*.sh; do
                            bash "$scanner" .
                        done
                    '''
                    // Tests de contrato de los scanners.
                    sh '''#!/usr/bin/env bash
                        set -euo pipefail
                        for test in scripts/security/test_*.sh; do
                            bash "$test"
                        done
                    '''
                }
            }
        }

        stage('Sincronizar entorno') {
            steps {
                sh 'uv sync --frozen'
            }
        }

        stage('Lint') {
            steps {
                sh 'uv run --frozen ruff check .'
            }
        }

        stage('Tests') {
            steps {
                sh 'uv run --frozen pytest -q'
            }
        }
    }

    post {
        always {
            echo "Resultado: ${currentBuild.currentResult}"
        }
        cleanup {
            deleteDir()
        }
    }
}

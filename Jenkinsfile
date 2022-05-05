pipeline {
    agent {
        docker {
            reuseNode false
            image 'caufieldjh/ubuntu20-python-3-8-5-dev:4-with-dbs-v6'
        }
    }
    // No scheduled builds for now
    //triggers{
    //    cron('H H 1 1-12 *')
    //}
    environment {
        BUILDSTARTDATE = sh(script: "echo `date +%Y%m%d`", returnStdout: true).trim()
        S3BUCKETNAME = 'kg-hub-public-data'
        S3PROJECTDIR = 'kg-bioportal' // no trailing slash
        MERGEDKGNAME_BASE = "kg_bioportal"
        MERGEDKGNAME_GENERIC = "merged-kg"

        // Ontologies to merge in this run, if not using --merge_all flag
        ONTOSET = 'CCONT,GRO-CPGA,STY,HP,PMO,CDPEO,GRO-CPD,ISO19115CC,TEDDY,NMOBR,IDQA,RDFS,LUNGMAP_M_CELL,PCO,ISSVA,IOBC,APADISORDERS,TESTEX,ONL-DP,XEO,EXTRACT,CHEMINF,ECSO,FAST-GENREFORM,VODANAKENYA,CTX,ISO19115DI,CARO,TEO,COMODI,IRD,OGDI,VEO,OHPI,GEXO,CIDO,GMM,RNAO,BCTT,MADS-RDF,GAZ,OBA,OSM,TRANS,BP-METADATA,PE,PCMO,UO,NMR,NEOMARK3,EVI,MCHVODANATERMS,EO1,APACOMPUTER,ICECI,DISDRIV,ONTONEO,ENM,ONTODM-CORE,UBERON,ISO19115TCC,SBO,CU-VO,SHR,ETHOPD,SPO,HOIP,ISO19115ROLES,DCT,WETAXTOPICS,PECO,IRDG,SEQ,HL7,SEDI,CASE-BASE-ONTO,AHOL,AD-DROP,TM-CONST,MATR,APATANDT,BCO,FLYGLYCODB,RXNORM,HOOM,HIO,PTS,CRISP,OCMR,TAXRANK,OMO,SO,ODNAE,ROCKNROLLTEST,GO,OBI,FOBI,PLANA,HIVO004,AGROMOP,ONTOPBM,ADMO,PCAO,EDAM,BE,ONE,CODO,FOVT,OCE,OFSMR,OMIM,KISAO,NOMEN,DEB,HCDR,ID-AMR,DERMLEX,BTO_ONTOLOGY,OBOREL,MOC,ALLERGYDETECTOR,ADALAB,MS,RDL,AERO,TML,MATRCOMPOUND,CEDARVS,PACO,MEGO,BRSO,TGMA,RPO,EHDAA2,GENO,MCBCC,HAMIDEHSGH,RNPRIO,FAST-TITLE,CWD,VODANA-MIGRANTS,AMINO-ACID,INTO,TADS,RCTONT,MIM,SITBAC,PP,OM,DLORO,ETANC,SIO,IMGT-ONTOLOGY,CLO,RVO,IDODEN,APO,HMIS033B,RXNO,MOOCCUADO,KENYAANC,UPA,EXO,OBS,SYMP,IBD,IAML-MOP,OBOE-SBC,EPO,FIX,OLATDV,OA,CONTSONTO,SNOMEDCT,NCBITAXON,ERO,ISO-ANNOTATIONS,BRCT,HRDO,MAMO,CHEAR,BCGO,RADLEX,MATRROCKIGNEOUS,MOSAIC,CYTO,PDO_CAS,PDO,AGROCYMAC,VODANA-UG,MIXSCV,FB-BT,CANCO,SD3,REPRODUCE-ME,BCS7,CN,NCCO,EP,PDQ,FENICS,VDOT,NEOMARK4,FISH-AST,EPIE,MA,PANET,TCO,CLAO,OGR,ODAE,PPO,NATPRO,FAST-EVENT-SKOS,WEAR,CVAO,GLYCORDF,ISO19108TO,CMPO,OAE,ISO19115PR,PIERO,MPO,TAO,PHMAMMADO,STO-DRAFT,NPOKB,EDAM-BIOIMAGING,CISAVIADO,ROLEO,DCM,ONTOPARON_SOCIAL,MNV,INFRARISK,NCRO,CDO,RNRMU,NMOSP,BCTEO,ONTOTOXNUC,DERMO,ICDO,WB-BT,ATO,VFB_DRIVERS,MDDB,NLN,GMO,SAO,EMAPA,BHN,DOID,OCRE,TCDO,TM-MER,ISO19115CON,GEOSPECIES,VARIO,UGANDA_DISEASES,SCIO,AHSO,TM-OTHER-FACTORS,KORO,ENVO,MCCV,ECG,UNITSONT,ONTOSINASC,ECAO,REX,NEO,AO,ACESO,FAST-FORMGENRE,EHDAA,LOINC,NERO,CLYH,MERA,ONTODM-KDD,PLIO,CANONT,TRAK,PO,PHYLONT,MOP,BSAO,OPTION-ONTOLOGY,ELD,CVDO,TDWGSPEC,RDA-ISSUANCE,TEST_A,FHHO,ZONMW-GENERIC,COHSI2STUDY,IDO-COVID-19,ADW,NIHSS,GFO,PEAO,DDPHENO,TRON,HAROREADO,CKDO,OARCS,LUNGMAP-HUMAN,ICO,HIVMT,PATEL,GLYCO,CARRE,EDDA_PT,suicideo,BRO,PATO,REXO,MMUSDV,BIOMO,ICD10,CHIRO,LAND-SURFACE,MLTX,GO-PLUS,OBIWS,DCAT-FDC,HOM,CHD,MCCL,MELO,NIFDYS,ONTOAVIDA,ECTO,HSO,PE-O,HUPSON,SOS,NCIT,PR,BIOMODELS,ESFO,MFO,LEPAO,BAO,EHDA,FIRE,ADO,ATC,REPO,JERM,EDDA,NMDCO,PHFUMIADO,COPDO,OMRSE,GRO,FYPO,LUNGMAP-MOUSE,TXPO,BDO'
    }
    options {
        timestamps()
        disableConcurrentBuilds()
    }
    stages {
        // Very first: pause for a minute to give a chance to
        // cancel and clean the workspace before use.
        stage('Ready and clean') {
            steps {
                // Give us a minute to cancel if we want.
                sleep time: 30, unit: 'SECONDS'
            }
        }

        stage('Initialize') {
            steps {
                // print some info
                dir('./gitrepo') {
                    sh 'env > env.txt'
                    sh 'echo $GIT_BRANCH > branch.txt'
                    sh 'echo "$GIT_BRANCH"'
                    sh 'cat env.txt'
                    sh 'cat branch.txt'
                    sh "echo $BUILDSTARTDATE > dow.txt"
                    sh "echo $BUILDSTARTDATE"
                    sh "echo $MERGEDKGNAME_BASE"
                    sh "echo $MERGEDKGNAME_GENERIC"
                    sh "python3.8 --version"
                    sh "id"
                    sh "whoami" // this should be jenkinsuser
                    // if the above fails, then the docker host didn't start the docker
                    // container as a user that this image knows about. This will
                    // likely cause lots of problems (like trying to write to $HOME
                    // directory that doesn't exist, etc), so we should fail here and
                    // have the user fix this

                }
            }
        }

        stage('Build kg_bioportal') {
            steps {
                dir('./gitrepo') {
                    git(
                            url: 'https://github.com/ncbo/kg-bioportal',
                            branch: 'main'
                    )
                    sh '/usr/bin/python3.8 -m venv venv'
                    sh '. venv/bin/activate'
                    // Now move on to the actual install + reqs
                    sh './venv/bin/pip install .'
                    sh './venv/bin/pip install awscli boto3 s3cmd'
                }
            }
        }

        // the download step uses s3cmd instead of the standard kghub_downloader
        // this is so we can access the private object

        stage('Download') {
            steps {
                dir('./gitrepo') {
                    script {
                        
                        // Verify that the project directory is defined, or it will make a mess
                        // when it uploads everything to the wrong directory
                        if (S3PROJECTDIR.replaceAll("\\s","") == '') {
                            error("Project name contains only whitespace. Will not continue.")
                        }
                        withCredentials([file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG')]) {
                            sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG get s3://$S3BUCKETNAME/frozen_incoming_data/bioportal_transformed/bioportal_transformed.tar.gz data/raw/bioportal_transformed.tar.gz'
                        }

                    }
                }
            }
        }

        // Transform step just moves and decompresses the raw sources
        
        stage('Transform') {
           steps {
               dir('./gitrepo') {
		           sh '. venv/bin/activate && env && mkdir ../BioPortal-to-KGX/ && mv data/raw/* ../BioPortal-to-KGX/ && tar -xvzf ../BioPortal-to-KGX/bioportal_transformed.tar.gz -C ../BioPortal-to-KGX/'
                           sh 'du -a ../BioPortal-to-KGX/'
		           sh 'pwd'
	       }
           }
        }

        // Currently using cat-merge
        stage('Merge') {
            steps {
                dir('./gitrepo') {
                    sh '. venv/bin/activate && python3.8 run.py catmerge --include_only $ONTOSET'
                    //sh 'cp merged_graph_stats.yaml merged_graph_stats_$BUILDSTARTDATE.yaml'
                    //sh 'tar -rvfz data/merged/merged-kg.tar.gz merged_graph_stats_$BUILDSTARTDATE.yaml'
                }
            }
        }

        stage('Publish') {
            steps {
                dir('./gitrepo') {
                    script {

                        // make sure we aren't going to clobber existing data
                        withCredentials([file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG')]) {
                            REMOTE_BUILD_DIR_CONTENTS = sh (
                                script: '. venv/bin/activate && s3cmd -c $S3CMD_CFG ls s3://$S3BUCKETNAME/$S3PROJECTDIR/$BUILDSTARTDATE/',
                                returnStdout: true
                            ).trim()
                            echo "REMOTE_BUILD_DIR_CONTENTS (THIS SHOULD BE EMPTY): '${REMOTE_BUILD_DIR_CONTENTS}'"
                            if("${REMOTE_BUILD_DIR_CONTENTS}" != ''){
                                echo "Will not overwrite existing remote S3 directory: $S3PROJECTDIR/$BUILDSTARTDATE"
                                sh 'exit 1'
                            } else {
                                echo "remote directory $S3PROJECTDIR/$BUILDSTARTDATE is empty, proceeding"
                            }
                        }

                        if (env.GIT_BRANCH != 'origin/main') {
                            echo "Will not push if not on main branch."
                        } else {
                            withCredentials([
					            file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG'),
					            file(credentialsId: 'aws_kg_hub_push_json', variable: 'AWS_JSON'),
					            string(credentialsId: 'aws_kg_hub_access_key', variable: 'AWS_ACCESS_KEY_ID'),
					            string(credentialsId: 'aws_kg_hub_secret_key', variable: 'AWS_SECRET_ACCESS_KEY')]) {
                                 
                                //
                                // make $BUILDSTARTDATE/ directory and sync to s3 bucket
                                // Don't create any index - none of this will be public
                                //
                                sh 'mkdir $BUILDSTARTDATE/'
                                sh 'cp -p data/merged/merged-kg.tar.gz $BUILDSTARTDATE/${MERGEDKGNAME_BASE}.tar.gz'
                                sh 'cp Jenkinsfile $BUILDSTARTDATE/'
                                // stats dir
                                //sh 'mkdir $BUILDSTARTDATE/stats/'
                                //sh 'cp -p *_stats.yaml $BUILDSTARTDATE/stats/'

                                sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG put -pr $BUILDSTARTDATE s3://$S3BUCKETNAME/$S3PROJECTDIR/'
                                sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG rm -r s3://$S3BUCKETNAME/$S3PROJECTDIR/current/'
                                sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG put -pr $BUILDSTARTDATE/* s3://$S3BUCKETNAME/$S3PROJECTDIR/current/'

                            }

                        }
                    }
                }
            }
        }

    }

    post {
        always {
            echo 'In always'
            echo 'Cleaning workspace...'
            cleanWs()
        }
        success {
            echo 'I succeeded!'
        }
        unstable {
            echo 'I am unstable :/'
        }
        failure {
            echo 'I failed :('
        }
        changed {
            echo 'Things were different before...'
        }
    }
}

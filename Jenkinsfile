pipeline {
    agent {
        docker {
            reuseNode false
            image 'caufieldjh/ubuntu20-python-3-9-14-dev:2'
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
                    sh "echo $BUILDSTARTDATE"
                    sh "echo $MERGEDKGNAME_BASE"
                    sh "python3.9 --version"
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
                    sh '/usr/bin/python3.9 -m venv venv'
                    sh '. venv/bin/activate'
                    sh './venv/bin/pip install .'
                    sh './venv/bin/pip install awscli boto3 s3cmd'
                }
            }
        }

        stage('Download') {
            steps {
                dir('./gitrepo') {
                    script {
                        // Get the names of all BioPortal ontologies
                        // This saves the list to data/raw/ontologylist.tsv
                        sh ". venv/bin/activate && kgbioportal get-ontology-list --api_key ${NCBO_API_KEY}"

                        // Now download all
                        // or at least in the future, do them all.
                        // For now just do a few
                        sh "printf 'ENVO\nPO\nSEPIO\n' > data/raw/ontologylist.tsv"
                        
                        // Download the ontologies
                        // This saves them to data/raw/
                        sh ". venv/bin/activate && kgbioportal download --api_key ${NCBO_API_KEY} --ontology_file data/raw/ontologylist.tsv"

                    }
                }
            }
        }

        // Transform the downloaded ontologies
        stage('Transform') {
           steps {
               dir('./gitrepo') {
		           sh ". venv/bin/activate && kgbioportal transform --input_dir data/raw/ --output_dir data/transformed/"
	       }
           }
        }

        stage('Publish') {
            steps {
                dir('./gitrepo') {
                    script {

                        if (env.GIT_BRANCH != 'origin/main') {
                            echo "Will not push if not on main branch."
                        } else {
                            withCredentials([
					            file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG'),
					            file(credentialsId: 'aws_kg_hub_push_json', variable: 'AWS_JSON'),
					            string(credentialsId: 'aws_kg_hub_access_key', variable: 'AWS_ACCESS_KEY_ID'),
					            string(credentialsId: 'aws_kg_hub_secret_key', variable: 'AWS_SECRET_ACCESS_KEY')]) {
                                 
                                // Index, then upload
                                sh '. venv/bin/activate && multi_indexer -v --directory data/transformed/ --prefix https://kghub.io/$S3PROJECTDIR/ -x -u'
                                sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG put -pr --acl-public --cf-invalidate data/transformed/ s3://kg-hub-public-data/$S3PROJECTDIR/'

                                // Now update the index for the whole project
                                sh '. venv/bin/activate && multi_indexer -v --prefix https://kghub.io/$S3PROJECTDIR/ -b kg-hub-public-data -r $S3PROJECTDIR -x'
                                sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG put -pr --acl-public --cf-invalidate ./index.html s3://kg-hub-public-data/$S3PROJECTDIR/'
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
